# Saleflow — ախտորոշում (2026-10-03)

## Ի՞նչ ստուգվեց

Վերարտադրվեց **պաշտոնական տեղադրիչի ճշգրիտ մեթոդը** sandbox-ում (Node v20.20.2, npx 10.8.2).

```bash
export AUTH_HEADER="Bearer <token>"
npx -y mcp-remote@latest "https://saleflow.pro/api/mcp" \
    --header "Authorization:${AUTH_HEADER}"
```

Արդյունքը.

```
[1384] Using custom headers: Authorization
[1384] Discovering OAuth server configuration...
[1384] Connecting to remote server: https://saleflow.pro/api/mcp
[1384] Using transport strategy: http-first
[1384] Connection error: SdkHttpError: Error POSTing to endpoint:
       {"error":"API token auth not enabled for this user"}
       code: 'CLIENT_HTTP_NOT_IMPLEMENTED', status: 403
```

**Նույն 403-ը, ինչ ուղիղ HTTP-ով։** Այսինքն՝ `mcp-remote`-ը ոչինչ չի փոխում —
նա էլ ուղարկում է ճիշտ նույն `Authorization: Bearer <token>` վերնագիրը։
Տեղադրիչը պարզապես ավտոմատացնում է Node-ի ներբեռնումը և կոնֆիգի գրառումը։

## Ապացույցների աղյուսակ

| Փորձ | Պատասխան |
|---|---|
| `Bearer <քո թոքենը>` | **403** `API token auth not enabled for this user` |
| `Bearer <64 զրո>` | **401** `Invalid API token` |
| առանց `Authorization` | **200** HTML (login էջ) |
| `Authorization: <raw token>` առանց `Bearer` | **200** HTML — սխեման չի ճանաչվում |
| `mcp-remote` (պաշտոնական ուղի) | **403** նույնը |

→ Թոքենը **վավեր է** (401-ը ուրիշ է), սխեման **ճիշտ է** (`Bearer`),
բայց սերվերը մերժում է **API-token ռեժիմը** հենց այս օգտատիրոջ համար։

## Ստուգված path-եր — 403-ը գլոբալ է

Բոլորը նույն 403-ը՝ `/api/me`, `/api/user`, `/api/v1/me`, `/api/health`, `/api/status`,
`/api/docs`, `/api/openapi.json`, `/api/swagger.json`, `/api/niches`, `/api/v1/niches`,
`/api/products`, `/api/v1/products`, `/api/mcp`, `/api/mcp/`, `/api/mcp/sse`, `/api/sse`,
`/api/v1/mcp`, `/api/mcp/tools`, `/api/mcp/info`, `/api/.well-known/oauth-protected-resource`

Իսկ `/`-ից դուրս ամեն ինչ (`/mcp`, `/sse`, `/mcp/sse`, `/mcp/v1`, `/.well-known/*`)
վերադարձնում է SPA-ի HTML-ը → **միակ իրական API դարպասը `/api/*`-ն է**։

## Երկու հնարավոր բացատրություն

1. **URL-ը այլ է։** Տեղադրիչը կարող է օգտագործել ուրիշ հասցե (ոչ `saleflow.pro/api/mcp`)։
   Ստուգվում է քո աշխատող կոնֆիգից։
2. **Թոքենը այլ հաշվից է։** Հնարավոր է՝ չատում ուղարկվածը այն չէ, որը
   տեղադրիչի մեջ է մտցված, կամ ստեղծվել է մինչև API-ի միացումը։

## Ինչպես ստուգել — հրաման քո մեքենայի վրա

Կոնֆիգը գտնվում է.

| ՕՀ | Ուղի |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

**macOS / Linux** — տպում է saleflow-ի գրառումը, թոքենը քողարկված.

```bash
python3 - <<'EOF'
import json, pathlib, re
p = pathlib.Path.home()/"Library/Application Support/Claude/claude_desktop_config.json"
d = json.loads(p.read_text())["mcpServers"]["saleflow"]
s = json.dumps(d, indent=2, ensure_ascii=False)
print(re.sub(r'[0-9a-f]{32,}', lambda m: m.group()[:4]+"…"+m.group()[-4:], s))
EOF
```

**Windows (PowerShell)**.

```powershell
$p = "$env:APPDATA\Claude\claude_desktop_config.json"
$d = (Get-Content $p -Raw | ConvertFrom-Json).mcpServers.saleflow
($d | ConvertTo-Json -Depth 9) -replace '[0-9a-f]{32,}', '***MASKED***'
```

Պետք է տեսնենք **`args`-ի մեջ եղած URL-ը** — հենց դա է պակասող տեղեկությունը։

## Վիճակը պրոյեկտում

- ✅ `SALEFLOW_TOKEN` → `.env` (`chmod 600`, zip-ից և git-ից դուրս)
- ✅ `.mcp.json` → **mcp-remote ձևաչափով**, ինչպես պաշտոնական տեղադրիչում; թոքենը ֆայլում չէ
- ✅ `python3 -m src.saleflow probe` → մեկ հրամանով ստուգում, միանալու պահին քաշում է `tools/list`
