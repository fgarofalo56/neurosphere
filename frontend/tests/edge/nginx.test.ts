/** PRP-29 item 5: the nginx edge template. Plain substring/line checks only. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// vitest runs with cwd = frontend.
const frontendDir = process.cwd();
const template = readFileSync(
  resolve(frontendDir, "nginx", "templates", "default.conf.template"),
  "utf8",
);
const mainConf = readFileSync(resolve(frontendDir, "nginx.conf"), "utf8");
const dockerfile = readFileSync(resolve(frontendDir, "Dockerfile"), "utf8");

/** Body of the `location <header> {` block (brace-balanced, no nesting in this file). */
function locationBlock(header: string): string {
  const start = template.indexOf(`location ${header} {`);
  expect(start).toBeGreaterThan(-1);
  const end = template.indexOf("\n    }", start);
  return template.slice(start, end);
}

describe("nginx edge template", () => {
  it("proxies /api/ to NS_UI_API_UPSTREAM with WebSocket upgrade headers", () => {
    const api = locationBlock("/api/");
    expect(api).toContain("proxy_pass ${NS_UI_API_UPSTREAM};");
    expect(api).toContain("proxy_http_version 1.1;");
    expect(api).toContain("proxy_set_header Upgrade $http_upgrade;");
    expect(api).toContain("proxy_set_header Connection $ns_connection_upgrade;");
    expect(api).toContain("proxy_set_header Host $proxy_host;");
    expect(api).not.toContain("proxy_set_header Host $host;");
    expect(api).toContain("proxy_ssl_server_name on;");
    expect(api).toContain("proxy_set_header X-Forwarded-Host $host;");
    expect(api).toContain("proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;");
    expect(api).toContain("proxy_set_header X-Forwarded-Proto $scheme;");
    expect(api).toContain("proxy_buffering off;");
    expect(template).toContain("map $http_upgrade $ns_connection_upgrade");
  });

  it("does not hard-code /readyz or /healthz; they come from the opt-in health include", () => {
    expect(template).not.toContain("location = /readyz");
    expect(template).not.toContain("location = /healthz");
    expect(template).toContain("include /tmp/ns-nginx/health.conf;");
  });

  it("sets no CORS headers (same origin)", () => {
    expect(template.toLowerCase()).not.toContain("access-control-allow-origin");
    expect(mainConf.toLowerCase()).not.toContain("access-control-allow-origin");
  });

  it("substitutes only NS_UI_API_UPSTREAM; every other $ is an nginx variable", () => {
    expect(template.match(/\$\{[A-Za-z_]+\}/g)?.every((m) => m === "${NS_UI_API_UPSTREAM}")).toBe(
      true,
    );
    expect(dockerfile).toContain("NGINX_ENVSUBST_FILTER=^NS_UI_");
  });

  it("keeps the security headers, SPA fallback and no-store config.json", () => {
    expect(template).toContain("add_header X-Content-Type-Options nosniff always;");
    expect(template).toContain("add_header Referrer-Policy no-referrer always;");
    expect(template).toContain("try_files $uri /index.html;");
    expect(locationBlock("= /config.json")).toContain(
      'add_header Cache-Control "no-store" always;',
    );
    expect(locationBlock("= /config.json")).toContain("try_files $uri @ns_rendered_config;");
  });

  it("is wired into the image: template, renderer, uid 10001, no baked config", () => {
    expect(mainConf).toContain("include /tmp/ns-conf.d/*.conf;");
    expect(dockerfile).toContain("/etc/nginx/templates/default.conf.template");
    expect(dockerfile).toContain("/docker-entrypoint.d/18-ns-render-config.sh");
    expect(dockerfile).toContain("USER 10001");
    expect(dockerfile).toContain("rm -f /usr/share/nginx/html/config.json");
  });
});
