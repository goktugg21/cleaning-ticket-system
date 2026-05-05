// Two HTTP+WS proxies inside the Playwright container.
//
//  127.0.0.1:18000 -> host.docker.internal:5173  (Vite, rewrites Host header
//                                                 to "localhost:5173" so
//                                                 Vite's allowedHosts guard
//                                                 does not 403)
//  127.0.0.1:8000  -> host.docker.internal:8000  (Django, Host rewritten to
//                                                 "localhost" so Django's
//                                                 ALLOWED_HOSTS accepts it,
//                                                 and CORS response headers
//                                                 are forced to the browser's
//                                                 Origin so axios calls from
//                                                 127.0.0.1:18000 succeed.)
import http from "node:http";
import net from "node:net";

function makeProxy({ listen, target, rewriteHost, forceCors }) {
  const server = http.createServer((clientReq, clientRes) => {
    if (forceCors && clientReq.method === "OPTIONS") {
      clientRes.writeHead(204, {
        "access-control-allow-origin": clientReq.headers.origin || "*",
        "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        "access-control-allow-headers":
          clientReq.headers["access-control-request-headers"] ||
          "authorization,content-type,accept",
        "access-control-max-age": "600",
        "vary": "origin",
      });
      clientRes.end();
      return;
    }
    const headers = { ...clientReq.headers, host: rewriteHost };
    const proxyReq = http.request(
      {
        host: target.host,
        port: target.port,
        method: clientReq.method,
        path: clientReq.url,
        headers,
      },
      (proxyRes) => {
        const outHeaders = { ...proxyRes.headers };
        if (forceCors) {
          outHeaders["access-control-allow-origin"] = clientReq.headers.origin || "*";
          outHeaders["vary"] = "origin";
        }
        clientRes.writeHead(proxyRes.statusCode, outHeaders);
        proxyRes.pipe(clientRes);
      },
    );
    proxyReq.on("error", (err) => {
      clientRes.writeHead(502, { "content-type": "text/plain" });
      clientRes.end(`bad gateway: ${err.message}`);
    });
    clientReq.pipe(proxyReq);
  });

  server.on("upgrade", (req, clientSocket, head) => {
    const upstream = net.connect(target.port, target.host, () => {
      const headerLines = [`${req.method} ${req.url} HTTP/${req.httpVersion}`];
      const lowered = { ...req.headers, host: rewriteHost };
      for (const [k, v] of Object.entries(lowered)) {
        if (Array.isArray(v)) for (const vv of v) headerLines.push(`${k}: ${vv}`);
        else headerLines.push(`${k}: ${v}`);
      }
      upstream.write(headerLines.join("\r\n") + "\r\n\r\n");
      if (head && head.length) upstream.write(head);
      upstream.pipe(clientSocket);
      clientSocket.pipe(upstream);
    });
    upstream.on("error", () => clientSocket.destroy());
    clientSocket.on("error", () => upstream.destroy());
  });

  server.listen(listen.port, listen.host, () => {
    console.log(
      `proxy listening on http://${listen.host}:${listen.port} -> http://${target.host}:${target.port} (Host=${rewriteHost}${forceCors ? ", CORS=force" : ""})`,
    );
  });
}

makeProxy({
  listen: { host: "127.0.0.1", port: 18000 },
  target: { host: "host.docker.internal", port: 5173 },
  rewriteHost: "localhost:5173",
});

makeProxy({
  listen: { host: "127.0.0.1", port: 8000 },
  target: { host: "host.docker.internal", port: 8000 },
  rewriteHost: "localhost",
  forceCors: true,
});
