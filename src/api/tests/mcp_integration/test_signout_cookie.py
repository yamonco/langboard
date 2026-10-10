import ast
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.responses import Response


@pytest.mark.parametrize("domain", ["yamon.io", ""])
@pytest.mark.parametrize("public_url", ["https://langboard.yamon.io", "http://localhost:5173"])
def test_signout_expires_the_same_cookie_scope_as_signin(domain: str, public_url: str) -> None:
    source = Path(__file__).parents[2] / "langboard/routes/auth/AuthApi.py"
    tree = ast.parse(source.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "sign_out")
    function.decorator_list = []
    scope = {
        "Env": SimpleNamespace(DOMAIN=domain, REFRESH_TOKEN_NAME="refresh", PUBLIC_UI_URL=public_url),
        "JsonResponse": Response,
        "status": SimpleNamespace(HTTP_202_ACCEPTED=202),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(source), "exec"), scope)
    response = scope["sign_out"]()
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    assert response.status_code == 202
    assert cookie["refresh"]["domain"] == domain
    assert cookie["refresh"]["path"] == "/"
    assert cookie["refresh"]["max-age"] == "0"
    assert bool(cookie["refresh"]["secure"]) == public_url.startswith("https://")
    assert cookie["refresh"]["httponly"]
