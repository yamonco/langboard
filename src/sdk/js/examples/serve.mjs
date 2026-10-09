// Local SDK example server only; production panel services own their CORS policy.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const root = new URL('../', import.meta.url);
createServer(async (request, response) => {
    try {
        const path = new URL(request.url, 'http://localhost').pathname;
        if (!['/index.mjs', '/examples/host.html', '/examples/panel.html'].includes(path)) {
            response.writeHead(404).end(); return;
        }
        const file = await readFile(fileURLToPath(new URL(path.slice(1), root)));
        response.writeHead(200, { 'Content-Type': path.endsWith('.mjs') ? 'text/javascript' : 'text/html', 'Access-Control-Allow-Origin': '*' });
        response.end(file);
    } catch { response.writeHead(500).end(); }
}).listen(8769, '127.0.0.1', () => console.log('Open http://127.0.0.1:8769/examples/host.html'));
