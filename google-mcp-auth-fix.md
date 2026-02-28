# Google MCP Authentication Fix

The Google MCPs need manual first-time authentication.

## Run These Commands ONE AT A TIME:

### 1. Google Drive
```bash
cd /tmp && npx @modelcontextprotocol/server-gdrive auth
```
Follow browser prompts → Sign in → Allow

### 2. Gmail  
```bash
cd /tmp && npx @gongrzhe/server-gmail-autoauth-mcp
```
Follow browser prompts → Sign in → Allow

### 3. Google Calendar
```bash
cd /tmp && GOOGLE_OAUTH_CREDENTIALS=~/.config/google-mcp/gcp-oauth.keys.json npx @cocal/google-calendar-mcp
```
Follow browser prompts → Sign in → Allow

After all 3 authenticate, restart Claude Desktop.

