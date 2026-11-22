
import jwt
from fastapi import HTTPException, Request
from starlette.responses import Response

SCOPE = "read:applications"
TOOLS = [
    {"name": "search_applications", "description": "Search the owner's tracked applications",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "maxLength": 200}}}},
    {"name": "get_application", "description": "Get one saved application by its ID",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
]
for tool in TOOLS:
    tool["annotations"] = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}


def install_mcp(app, settings, db):
    import json

    issuer = f"https://{settings.auth0_domain}/"
    keys = jwt.PyJWKClient(issuer + ".well-known/jwks.json", timeout=5)
    metadata_url = settings.app_url + "/.well-known/oauth-protected-resource/mcp"

    @app.get("/.well-known/oauth-protected-resource")
    @app.get("/.well-known/oauth-protected-resource/mcp")
    def metadata():
        if not settings.auth0_domain:
            raise HTTPException(404)
        return {"resource": settings.mcp_audience, "authorization_servers": [issuer],
                "scopes_supported": [SCOPE], "bearer_methods_supported": ["header"]}

    @app.get("/mcp")
    def stream():
        raise HTTPException(405, headers={"Allow": "POST"})

    @app.post("/mcp")
    def rpc(request: Request, message: dict):
        challenge = {"WWW-Authenticate": f'Bearer resource_metadata="{metadata_url}", scope="{SCOPE}"'}
        if request.headers.get("origin") not in (None, settings.app_url):
            raise HTTPException(403)
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if not settings.auth0_domain or not settings.owner_subject or scheme.lower() != "bearer" or not token:
            raise HTTPException(401, headers=challenge)
        try:
            if jwt.get_unverified_header(token).get("alg") != "RS256":
                raise jwt.InvalidAlgorithmError()
            key = keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=settings.mcp_audience,
                                issuer=issuer, options={"require": ["exp", "sub", "iat"]})
        except jwt.PyJWTError:
            raise HTTPException(401, headers=challenge) from None
        owner = claims["sub"]
        if owner != settings.owner_subject or SCOPE not in str(claims.get("scope", "")).split():
            raise HTTPException(403, headers=challenge)
        response = {"jsonrpc": "2.0", "id": message.get("id")}
        method = message.get("method")
        params = message.get("params", {})
        if message.get("jsonrpc") != "2.0" or not isinstance(params, dict) or not isinstance(method, str):
            return {**response, "error": {"code": -32600, "message": "Invalid Request"}}
        if "id" not in message:
            return Response(status_code=202)
        if method == "initialize":
            supported = ("2025-03-26", "2025-06-18", "2025-11-25")
            version = params.get("protocolVersion")
            result = {"protocolVersion": version if version in supported else supported[-1],
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "internship-dashboard", "version": "0.1.0"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name, args = params.get("name"), params.get("arguments", {})
            if not isinstance(args, dict):
                return {**response, "error": {"code": -32602, "message": "Invalid tool arguments"}}
            if name == "search_applications" and isinstance(args.get("query", ""), str):
                term = f"%{args.get('query', '')[:200]}%"
                data = db.all("""SELECT id,status,deadline,updated_at,json_extract(posting,'$.title') title,
                              json_extract(posting,'$.company') company FROM applications
                              WHERE owner=? AND (title LIKE ? OR company LIKE ?) ORDER BY updated_at DESC LIMIT 40""",
                              (owner, term, term))
            elif name == "get_application" and isinstance(args.get("id"), str):
                data = db.one("""SELECT id,status,notes,deadline,posting,updated_at,submitted_version
                              FROM applications WHERE owner=? AND id=?""", (owner, args["id"]))
                if data:
                    data["posting"] = json.loads(data["posting"])
            else:
                return {**response, "error": {"code": -32602, "message": "Unknown tool or invalid arguments"}}
            result = {"content": [{"type": "text", "text": json.dumps(data)}]}
        else:
            return {**response, "error": {"code": -32601, "message": "Method not found"}}
        return {**response, "result": result}
