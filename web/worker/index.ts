import handler from "vinext/server/fetch-handler";
import { runWithConnectorBinding } from "../lib/connector-context";
import type { ConnectorBinding } from "../lib/connector-contract.mjs";
import { deskApi } from "../lib/desk-api";

const worker = {
  fetch(request: Request, env: Cloudflare.Env, ctx: ExecutionContext<{ CONNECTORS?: ConnectorBinding }>) {
    if (new URL(request.url).pathname.startsWith('/api/desk')) {
      return deskApi(request, env.BUCKET).catch(() => Response.json({error:'자료 처리에 실패했습니다. 다시 시도해 주세요.'},{status:500}));
    }
    let binding = ctx.props?.CONNECTORS;
    // Local preview emulates the same request-scoped capability. This branch and
    // the auxiliary service binding are absent from production builds.
    if (import.meta.env.DEV && !binding && env.CONNECTORS) {
      const preview = env.CONNECTORS;
      const expiresAt = Date.now() + 60_000;
      binding = {
        async getContext() {
          if (Date.now() >= expiresAt) return { status: "request_context_expired" };
          return preview.getContext?.() ?? { status: "binding_unavailable" };
        },
        async invoke(connectorId, actionName, args) {
          if (Date.now() >= expiresAt) {
            return { status: "request_context_expired", message: "This request has expired. Please try again." };
          }
          return preview.invoke(connectorId, actionName, args);
        },
      };
    }
    return runWithConnectorBinding(binding, async () => {
      const response = await handler.fetch(request, env, ctx);
      // Personalized dashboard HTML must not retain references to assets from an
      // older deployment. Hashed static assets keep their framework cache rules.
      if (response.headers.get('content-type')?.includes('text/html')) {
        const fresh = new Response(response.body, response);
        fresh.headers.set('Cache-Control', 'private, no-store');
        return fresh;
      }
      return response;
    });
  },
};

export default worker;
