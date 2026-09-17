#!/usr/bin/env node
// Zero-dependency dev server: serves the static frontend and proxies /api/*
// to a real IRIS instance, so the browser sees everything as same-origin
// (matching production, where this app is served BY IRIS itself) and no CORS
// configuration is needed for local development.
//
// Usage:
//   node dev-server.mjs [--port 8080] [--target http://localhost:52773]
// or:
//   PORT=8080 IRIS_URL=http://localhost:52773 node dev-server.mjs

import http from 'node:http';
import https from 'node:https';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function arg(name, fallback) {
  const idx = process.argv.indexOf(`--${name}`);
  if (idx !== -1 && process.argv[idx + 1]) return process.argv[idx + 1];
  return fallback;
}

const PORT = Number(arg('port', process.env.PORT || 8080));
const TARGET = arg('target', process.env.IRIS_URL || 'http://localhost:52773');
const targetUrl = new URL(TARGET);

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.woff2': 'font/woff2',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
};

function serveStatic(req, res) {
  let filePath = decodeURIComponent(req.url.split('?')[0]);
  if (filePath === '/') filePath = '/index.html';
  const fullPath = path.join(__dirname, filePath);

  if (!fullPath.startsWith(__dirname)) {
    res.writeHead(403).end('Forbidden');
    return;
  }

  fs.readFile(fullPath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain' }).end('Not found');
      return;
    }
    const ext = path.extname(fullPath);
    res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'application/octet-stream' });
    res.end(data);
  });
}

function proxyToIris(req, res) {
  const client = targetUrl.protocol === 'https:' ? https : http;
  const proxyReq = client.request(
    {
      protocol: targetUrl.protocol,
      hostname: targetUrl.hostname,
      port: targetUrl.port,
      path: req.url,
      method: req.method,
      headers: { ...req.headers, host: targetUrl.host },
      rejectUnauthorized: false,
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(res);
    }
  );
  proxyReq.on('error', (err) => {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: { summary: `Proxy error reaching ${TARGET}: ${err.message}` } }));
  });
  req.pipe(proxyReq);
}

const server = http.createServer((req, res) => {
  if (req.url.startsWith('/api/')) {
    proxyToIris(req, res);
  } else {
    serveStatic(req, res);
  }
});

server.listen(PORT, () => {
  console.log(`IRIS Command Center dev server running at http://localhost:${PORT}`);
  console.log(`Proxying /api/* to ${TARGET}`);
});
