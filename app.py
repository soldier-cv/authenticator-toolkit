"""
Authenticator Toolkit - Web Version
Google Authenticator 数据解码与 TOTP 动态码生成工具
Based on soldier-cv/google-authenticator-exporter
"""
import os
import io
import base64
import struct
import sqlite3
import urllib.parse
from datetime import datetime
from functools import wraps
from flask import Flask, request, render_template, jsonify
from PIL import Image
import pyotp

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# ============ Rate Limiter (SQLite) ============
# Configurable via environment variables
DAILY_LIMIT = int(os.environ.get('RATE_LIMIT_DAILY', 50))
DB_PATH = os.environ.get('RATE_LIMIT_DB', '/data/usage.db')


class RateLimiter:
    """Per-IP rate limiter using SQLite. Tracks daily usage only."""

    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent read/write
        return conn

    def _init_db(self):
        conn = self._get_conn()
        conn.execute('''CREATE TABLE IF NOT EXISTS usage (
            ip TEXT PRIMARY KEY,
            daily_count INTEGER NOT NULL DEFAULT 0,
            last_date TEXT
        )''')
        conn.commit()
        conn.close()

    def _reset_if_needed(self, conn, row, today):
        """Reset daily counter if date changed."""
        ip, dc, ld = row
        if ld != today:
            dc = 0
            conn.execute(
                "UPDATE usage SET daily_count=?, last_date=? WHERE ip=?",
                (dc, today, ip)
            )
        return dc

    def check_and_record(self, ip):
        """Check rate limits for IP. Returns (allowed, error_msg, limits_info)."""
        now = datetime.utcnow()
        today = now.strftime('%Y-%m-%d')

        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT ip, daily_count, last_date FROM usage WHERE ip=?", (ip,)
            ).fetchone()

            if row:
                dc = self._reset_if_needed(conn, row, today)
            else:
                dc = 0

            limits_info = {
                'daily': f'{dc}/{DAILY_LIMIT}'
            }

            # Check limits
            if dc >= DAILY_LIMIT:
                return False, f'Daily limit reached ({DAILY_LIMIT}/day)', limits_info

            # Increment counter
            if row:
                conn.execute(
                    "UPDATE usage SET daily_count=daily_count+1, last_date=? WHERE ip=?",
                    (today, ip)
                )
            else:
                conn.execute(
                    "INSERT INTO usage (ip, daily_count, last_date) VALUES (?, 1, ?)",
                    (ip, today)
                )
            conn.commit()

            limits_info = {
                'daily': f'{dc + 1}/{DAILY_LIMIT}'
            }

            return True, None, limits_info
        finally:
            conn.close()


import time as _time
_start_time = _time.time()

rate_limiter = RateLimiter(DB_PATH)


def get_client_ip():
    """Get real client IP (support reverse proxy headers)."""
    # X-Forwarded-For for reverse proxy (OnePanel/Nginx/FRP)
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'

# ============ Protobuf Manual Decoder ============
# Since the proto is simple, we decode manually to avoid grpcio-tools dependency

class ProtobufDecoder:
    """Minimal protobuf decoder for Google Auth MigrationPayload"""
    
    WIRETYPE_VARINT = 0
    WIRETYPE_64BIT = 1
    WIRETYPE_LEN = 2
    WIRETYPE_32BIT = 5
    
    @staticmethod
    def read_varint(data, pos):
        result = 0
        shift = 0
        while pos < len(data):
            b = data[pos]
            result |= (b & 0x7F) << shift
            pos += 1
            if (b & 0x80) == 0:
                break
            shift += 7
        return result, pos
    
    @staticmethod
    def decode_message(data):
        """Decode protobuf message into dict of {field_number: value}"""
        fields = {}
        pos = 0
        while pos < len(data):
            # Read tag
            tag, pos = ProtobufDecoder.read_varint(data, pos)
            field_number = tag >> 3
            wire_type = tag & 0x07
            
            if wire_type == ProtobufDecoder.WIRETYPE_VARINT:
                value, pos = ProtobufDecoder.read_varint(data, pos)
                fields.setdefault(field_number, []).append(value)
            elif wire_type == ProtobufDecoder.WIRETYPE_LEN:
                length, pos = ProtobufDecoder.read_varint(data, pos)
                value = data[pos:pos+length]
                pos += length
                fields.setdefault(field_number, []).append(value)
            elif wire_type == ProtobufDecoder.WIRETYPE_64BIT:
                value = struct.unpack('<Q', data[pos:pos+8])[0]
                pos += 8
                fields.setdefault(field_number, []).append(value)
            elif wire_type == ProtobufDecoder.WIRETYPE_32BIT:
                value = struct.unpack('<I', data[pos:pos+4])[0]
                pos += 4
                fields.setdefault(field_number, []).append(value)
            else:
                break
        return fields

def decode_otp_parameters(data):
    """Decode OtpParameters message
    message OtpParameters {
        bytes secret = 1;
        string name = 2;
        string issuer = 3;
        Algorithm algorithm = 4;  // enum
        DigitCount digits = 5;    // enum
        OtpType type = 6;         // enum
        int64 counter = 7;
        string unique_id = 8;
    }
    """
    fields = ProtobufDecoder.decode_message(data)
    
    result = {}
    
    # Field 1: secret (bytes)
    if 1 in fields:
        v = fields[1][0]
        result['secret'] = v if isinstance(v, bytes) else str(v).encode('utf-8')
    
    # Field 2: name (string)
    if 2 in fields:
        v = fields[2][0]
        result['name'] = v.decode('utf-8', errors='replace') if isinstance(v, bytes) else str(v)
    
    # Field 3: issuer (string)
    if 3 in fields:
        v = fields[3][0]
        result['issuer'] = v.decode('utf-8', errors='replace') if isinstance(v, bytes) else str(v)
    
    # Field 4: algorithm (enum)
    ALGORITHM_MAP = {0: 'UNSPECIFIED', 1: 'SHA1', 2: 'SHA256', 3: 'SHA512', 4: 'MD5'}
    if 4 in fields:
        result['algorithm'] = ALGORITHM_MAP.get(fields[4][0], f'UNKNOWN({fields[4][0]})')
    
    # Field 5: digits (enum)
    DIGITS_MAP = {0: 0, 1: 6, 2: 8, 3: 7}
    if 5 in fields:
        result['digits'] = DIGITS_MAP.get(fields[5][0], fields[5][0])
    
    # Field 6: type (enum)
    TYPE_MAP = {0: 'UNSPECIFIED', 1: 'HOTP', 2: 'TOTP'}
    if 6 in fields:
        result['type'] = TYPE_MAP.get(fields[6][0], f'UNKNOWN({fields[6][0]})')
    
    # Field 7: counter (int64)
    if 7 in fields:
        result['counter'] = fields[7][0]
    
    # Field 8: unique_id (string)
    if 8 in fields:
        v = fields[8][0]
        result['unique_id'] = v.decode('utf-8', errors='replace') if isinstance(v, bytes) else str(v)
    
    return result

def decode_migration_payload(data):
    """Decode MigrationPayload
    message MigrationPayload {
        repeated OtpParameters otp_parameters = 1;
        int32 version = 2;
        int32 batch_size = 3;
        int32 batch_index = 4;
        int32 batch_id = 5;
    }
    """
    fields = ProtobufDecoder.decode_message(data)
    
    result = {
        'version': fields.get(2, [0])[0],
        'batch_size': fields.get(3, [1])[0],
        'batch_index': fields.get(4, [0])[0],
        'batch_id': fields.get(5, [0])[0],
        'otp_parameters': []
    }
    
    # Field 1: repeated OtpParameters
    if 1 in fields:
        for otp_data in fields[1]:
            result['otp_parameters'].append(decode_otp_parameters(otp_data))
    
    return result

# ============ Base32 Encoder (RFC 3548) ============

def to_base32(data_bytes):
    """Convert bytes to base32 string (RFC 3548)"""
    import base64
    return base64.b32encode(data_bytes).decode('ascii').rstrip('=')

# ============ URI Decoder ============

def decode_export_uri(uri):
    """Decode otpauth-migration://offline?data=... URI"""
    parsed = urllib.parse.urlparse(uri)
    params = urllib.parse.parse_qs(parsed.query)
    
    if 'data' not in params:
        raise ValueError("No 'data' parameter found in URI")
    
    data_b64 = params['data'][0]
    # URL-decode if needed
    data_b64 = urllib.parse.unquote(data_b64)
    
    # Add padding if needed
    padding = 4 - len(data_b64) % 4
    if padding != 4:
        data_b64 += '=' * padding
    
    # Base64 decode
    raw_data = base64.b64decode(data_b64)
    
    # Decode protobuf
    payload = decode_migration_payload(raw_data)
    
    # Convert secrets to base32
    accounts = []
    for otp in payload['otp_parameters']:
        account = {
            'name': otp.get('name', ''),
            'issuer': otp.get('issuer', ''),
            'secret_base32': to_base32(otp.get('secret', b'')),
            'algorithm': otp.get('algorithm', 'SHA1'),
            'digits': otp.get('digits', 6),
            'type': otp.get('type', 'TOTP'),
            'counter': otp.get('counter', 0),
        }
        accounts.append(account)
    
    return {
        'version': payload['version'],
        'batch_size': payload['batch_size'],
        'batch_index': payload['batch_index'],
        'accounts': accounts
    }

# ============ QR Code Reader ============

def read_qr_from_image(image_bytes):
    """Read QR code from image bytes using pyzbar"""
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
        img = Image.open(io.BytesIO(image_bytes))
        decoded = pyzbar_decode(img)
        
        results = []
        for obj in decoded:
            if obj.type == 'QRCODE':
                results.append(obj.data.decode('utf-8'))
        return results
    except ImportError:
        # Fallback: try qreader
        try:
            from qreader import QReader
            import cv2
            import numpy as np
            
            img_array = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            
            reader = QReader()
            decoded = reader.detect_and_decode(img)
            return [d for d in decoded if d]
        except Exception as e:
            raise RuntimeError(f"No QR decoder available. Install pyzbar or qreader. Error: {e}")

# ============ Flask Routes ============

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/decode', methods=['POST'])
def decode():
    try:
        # Rate limit check
        client_ip = get_client_ip()
        allowed, error_msg, limits_info = rate_limiter.check_and_record(client_ip)
        if not allowed:
            return jsonify({
                'error': error_msg,
                'limits': limits_info,
                'retry_after': 'tomorrow'
            }), 429
        
        # Check if file was uploaded
        if 'qr_image' in request.files:
            file = request.files['qr_image']
            if file.filename:
                image_bytes = file.read()
                qr_texts = read_qr_from_image(image_bytes)
                
                if not qr_texts:
                    return jsonify({'error': 'No QR code found in image'}), 400
                
                # Process all QR codes found
                all_accounts = []
                for qr_text in qr_texts:
                    if qr_text.startswith('otpauth-migration://'):
                        result = decode_export_uri(qr_text)
                        all_accounts.extend(result['accounts'])
                    else:
                        return jsonify({'error': f'Invalid QR code: not a Google Authenticator export. Got: {qr_text[:100]}...'}), 400
                
                return jsonify({'accounts': all_accounts})
        
        # Check if URI was pasted
        if 'uri' in request.form:
            uri = request.form['uri'].strip()
            if uri:
                if not uri.startswith('otpauth-migration://'):
                    return jsonify({'error': 'Invalid URI: must start with otpauth-migration://'}), 400
                result = decode_export_uri(uri)
                return jsonify(result)
        
        return jsonify({'error': 'No file or URI provided'}), 400
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/generate', methods=['POST'])
def generate():
    """Generate TOTP code from secret key."""
    try:
        # Rate limit check
        client_ip = get_client_ip()
        allowed, error_msg, limits_info = rate_limiter.check_and_record(client_ip)
        if not allowed:
            return jsonify({
                'error': error_msg,
                'limits': limits_info,
                'retry_after': 'tomorrow'
            }), 429

        data = request.get_json(silent=True) or {}
        secret = data.get('secret', '').strip()

        if not secret:
            return jsonify({'error': 'Secret key is required'}), 400

        # Validate secret format
        try:
            # Test if secret is valid base32
            base64.b32decode(secret + '=' * (-len(secret) % 4))
        except Exception:
            return jsonify({'error': 'Invalid secret key format (must be base32 encoded)'}), 400

        algorithm = data.get('algorithm', 'SHA1').upper()
        if algorithm not in ('SHA1', 'SHA256', 'SHA512', 'MD5'):
            return jsonify({'error': f'Unsupported algorithm: {algorithm}. Supported: SHA1, SHA256, SHA512, MD5'}), 400

        digits = data.get('digits', 6)
        try:
            digits = int(digits)
            if digits not in (6, 7, 8):
                return jsonify({'error': f'Invalid digits: {digits}. Supported: 6, 7, 8'}), 400
        except (ValueError, TypeError):
            return jsonify({'error': 'digits must be an integer'}), 400

        period = data.get('period', 30)
        try:
            period = int(period)
            if period <= 0 or period > 300:
                return jsonify({'error': f'Invalid period: {period}. Must be between 1 and 300 seconds'}), 400
        except (ValueError, TypeError):
            return jsonify({'error': 'period must be an integer'}), 400

        # Map algorithm names to hashlib
        algo_map = {
            'SHA1': 'sha1',
            'SHA256': 'sha256',
            'SHA512': 'sha512',
            'MD5': 'md5'
        }

        totp = pyotp.TOTP(secret, digits=digits, digest=algo_map.get(algorithm, 'sha1'), interval=period)
        current_code = totp.now()
        remaining = totp.interval - (datetime.utcnow().timestamp() % totp.interval)

        return jsonify({
            'code': current_code,
            'algorithm': algorithm,
            'digits': digits,
            'period': period,
            'remaining_seconds': int(remaining),
            'remaining_percent': round((remaining / period) * 100, 1)
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/generate/batch', methods=['POST'])
def generate_batch():
    """Generate TOTP codes for multiple secrets. Rate limit counts as one request."""
    try:
        # Rate limit check — batch counts as one request
        client_ip = get_client_ip()
        allowed, error_msg, limits_info = rate_limiter.check_and_record(client_ip)
        if not allowed:
            return jsonify({
                'error': error_msg,
                'limits': limits_info,
                'retry_after': 'tomorrow'
            }), 429

        data = request.get_json(silent=True) or {}
        items = data.get('items', [])

        if not items:
            return jsonify({'error': 'items array is required'}), 400

        if len(items) > 20:
            return jsonify({'error': 'Maximum 20 items per batch request'}), 400

        algo_map = {
            'SHA1': 'sha1',
            'SHA256': 'sha256',
            'SHA512': 'sha512',
            'MD5': 'md5'
        }

        results = []
        for idx, item in enumerate(items):
            entry = {'index': idx}
            try:
                secret = (item.get('secret') or '').strip()
                if not secret:
                    raise ValueError('Secret key is required')

                # Validate base32
                try:
                    base64.b32decode(secret + '=' * (-len(secret) % 4))
                except Exception:
                    raise ValueError('Invalid secret key format (must be base32 encoded)')

                algorithm = item.get('algorithm', 'SHA1').upper()
                if algorithm not in ('SHA1', 'SHA256', 'SHA512', 'MD5'):
                    raise ValueError(f'Unsupported algorithm: {algorithm}')

                digits = int(item.get('digits', 6))
                if digits not in (6, 7, 8):
                    raise ValueError(f'Invalid digits: {digits}')

                period = int(item.get('period', 30))
                if period <= 0 or period > 300:
                    raise ValueError(f'Invalid period: {period}')

                totp = pyotp.TOTP(secret, digits=digits, digest=algo_map.get(algorithm, 'sha1'), interval=period)
                current_code = totp.now()
                remaining = totp.interval - (datetime.utcnow().timestamp() % totp.interval)

                entry['code'] = current_code
                entry['algorithm'] = algorithm
                entry['digits'] = digits
                entry['period'] = period
                entry['remaining_seconds'] = int(remaining)
                entry['remaining_percent'] = round((remaining / period) * 100, 1)

            except Exception as e:
                entry['error'] = str(e)

            results.append(entry)

        return jsonify({'results': results}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    """Health check endpoint with diagnostics for Docker HEALTHCHECK and monitoring."""
    import time
    try:
        # Verify rate limiter DB is accessible
        conn = rate_limiter._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM usage").fetchone()
        total_records = row[0] if row else 0
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False
        total_records = -1

    status_code = 200 if db_ok else 503

    return jsonify({
        'status': 'ok' if db_ok else 'degraded',
        'uptime_seconds': int(time.time() - _start_time),
        'rate_limiter': {
            'db_healthy': db_ok,
            'total_records': total_records,
            'daily_limit': DAILY_LIMIT,
        },
    }), status_code

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
