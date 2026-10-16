import os
import sys
import subprocess
import base64
import pytest
import pyotp

# Ensure test credentials and test db exist in environment before importing app
TEST_USER = os.environ.get('TOTP_ACCESS_USER', 'admin')
TEST_PASSWORD = os.environ.get('TOTP_ACCESS_PASSWORD', 'test_auth_pwd_998')
os.environ.setdefault('TOTP_ACCESS_USER', TEST_USER)
os.environ.setdefault('TOTP_ACCESS_PASSWORD', TEST_PASSWORD)
os.environ.setdefault('RATE_LIMIT_DB', '/tmp/authtk_test_usage.db')

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import app as app_module
from app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def auth_headers():
    token = base64.b64encode(f"{TEST_USER}:{TEST_PASSWORD}".encode('utf-8')).decode('ascii')
    return {'Authorization': f'Basic {token}'}


def test_unconfigured_password_fails_closed():
    """断言未配置口令/哈希时，模块加载立即拒绝启动并报错到 stderr (fail-closed)。"""
    # 场景 1: 完全不提供环境变量
    env_clean = os.environ.copy()
    env_clean.pop('TOTP_ACCESS_PASSWORD', None)
    env_clean.pop('TOTP_ACCESS_PASSWORD_HASH', None)

    res = subprocess.run(
        [sys.executable, "-c", "import app"],
        capture_output=True,
        text=True,
        env=env_clean,
        cwd=REPO_ROOT
    )
    assert res.returncode != 0, "未配置口令时，退出码必须非 0"
    assert "fail-closed" in res.stderr, "stderr 必须包含 fail-closed 提示"

    # 场景 2: 提供空字符串
    env_empty = os.environ.copy()
    env_empty['TOTP_ACCESS_PASSWORD'] = ''
    env_empty['TOTP_ACCESS_PASSWORD_HASH'] = ''

    res_empty = subprocess.run(
        [sys.executable, "-c", "import app"],
        capture_output=True,
        text=True,
        env=env_empty,
        cwd=REPO_ROOT
    )
    assert res_empty.returncode != 0, "口令为空字符串时，退出码必须非 0"
    assert "fail-closed" in res_empty.stderr, "stderr 必须包含 fail-closed 提示"


def test_unauthenticated_requests_return_401(client):
    """断言所有业务路由在无凭证时均返回 401 且包含 WWW-Authenticate 挑战头。"""
    protected_endpoints = [
        ('GET', '/'),
        ('POST', '/decode'),
        ('POST', '/generate'),
        ('POST', '/generate/batch')
    ]

    for method, path in protected_endpoints:
        if method == 'GET':
            res = client.get(path)
        else:
            res = client.post(path)

        assert res.status_code == 401, f"{method} {path} 未鉴权时必须返回 401"
        assert res.headers.get('WWW-Authenticate') == 'Basic realm="Authenticator Toolkit"'
        json_data = res.get_json()
        assert json_data == {'error': 'authentication required'}
        assert TEST_PASSWORD not in res.data.decode('utf-8', errors='ignore')


def test_wrong_credentials_timing_and_byte_identical_401(client):
    """断言错误口令与错误用户名均返回 401 且响应逐字节一致，不泄露账号存在性。"""
    auth_wrong_pwd = "Basic " + base64.b64encode(f"{TEST_USER}:definitely_wrong_pwd".encode('utf-8')).decode('ascii')
    auth_wrong_user = "Basic " + base64.b64encode(f"nonexistent_user:{TEST_PASSWORD}".encode('utf-8')).decode('ascii')

    # GET / 路由测试
    r_wrong_pwd = client.get('/', headers={'Authorization': auth_wrong_pwd})
    r_wrong_user = client.get('/', headers={'Authorization': auth_wrong_user})

    assert r_wrong_pwd.status_code == 401
    assert r_wrong_user.status_code == 401
    assert r_wrong_pwd.data == r_wrong_user.data, "错误口令与错误用户名的响应体必须逐字节一致"
    assert r_wrong_pwd.headers.get('WWW-Authenticate') == r_wrong_user.headers.get('WWW-Authenticate')

    # POST /generate 路由测试
    r_post_wrong_pwd = client.post('/generate', json={"secret": "JBSWY3DPEHPK3PXP"}, headers={'Authorization': auth_wrong_pwd})
    r_post_wrong_user = client.post('/generate', json={"secret": "JBSWY3DPEHPK3PXP"}, headers={'Authorization': auth_wrong_user})

    assert r_post_wrong_pwd.status_code == 401
    assert r_post_wrong_user.status_code == 401
    assert r_post_wrong_pwd.data == r_post_wrong_user.data, "POST 端点上两者响应体必须逐字节一致"


def test_authenticated_requests_succeed(client, auth_headers):
    """断言正确凭证下业务端点均可正常访问且计算结果与 pyotp 一致。"""
    # 1. 访问首页
    r_index = client.get('/', headers=auth_headers)
    assert r_index.status_code == 200
    assert "<!doctype html" in r_index.data.decode('utf-8').lower() or "<html" in r_index.data.decode('utf-8').lower()

    # 2. 单个 TOTP 生成
    secret = "JBSWY3DPEHPK3PXP"
    r_gen = client.post('/generate', json={"secret": secret}, headers=auth_headers)
    assert r_gen.status_code == 200
    gen_data = r_gen.get_json()
    assert 'code' in gen_data
    expected_code = pyotp.TOTP(secret).now()
    assert gen_data['code'] == expected_code
    assert gen_data['digits'] == 6
    assert gen_data['algorithm'] == 'SHA1'

    # 3. 批量 TOTP 生成
    r_batch = client.post('/generate/batch', json={"items": [{"secret": secret}]}, headers=auth_headers)
    assert r_batch.status_code == 200
    batch_data = r_batch.get_json()
    assert len(batch_data['results']) == 1
    assert batch_data['results'][0]['code'] == expected_code


def test_health_endpoint_unauthenticated_and_no_leak(client):
    """断言 /health 免鉴权 200，且响应键集合不包含敏感字段。"""
    res = client.get('/health')
    assert res.status_code == 200
    data = res.get_json()
    assert "status" in data
    assert "rate_limiter" in data

    forbidden_substrings = ['secret', 'token', 'password', 'key']

    def assert_no_sensitive_keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                k_lower = k.lower()
                for forbidden in forbidden_substrings:
                    assert forbidden not in k_lower, f"键名 '{k}' 含有敏感词 '{forbidden}'"
                assert_no_sensitive_keys(v)
        elif isinstance(node, list):
            for item in node:
                assert_no_sensitive_keys(item)

    assert_no_sensitive_keys(data)


def test_rate_limiter_functional_regression(client, auth_headers):
    """断言限流器保持正常工作（超限返回 429）。"""
    assert app_module.rate_limiter is not None
    assert app_module.DAILY_LIMIT == int(os.environ.get('RATE_LIMIT_DAILY', 50))

    # 使用独立 IP 模拟超出限制
    test_ip = "198.51.100.42"
    for _ in range(app_module.DAILY_LIMIT):
        app_module.rate_limiter.check_and_record(test_ip)

    res = client.post(
        '/decode',
        headers={**auth_headers, 'X-Forwarded-For': test_ip},
        data={'uri': 'otpauth-migration://offline?data=test'}
    )
    assert res.status_code == 429
    data = res.get_json()
    assert "Daily limit reached" in data.get('error', '')


def test_defensive_cleared_hash_fails_closed():
    """断言防御性双保险：运行期若 _EXPECTED_HASH 为空直接拒绝鉴权。"""
    orig_hash = app_module._EXPECTED_HASH
    try:
        app_module._EXPECTED_HASH = None
        assert app_module.verify_password(TEST_USER, TEST_PASSWORD) is False
    finally:
        app_module._EXPECTED_HASH = orig_hash
