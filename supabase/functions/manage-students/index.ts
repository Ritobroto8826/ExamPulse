import { handleRequest } from "./handler.ts";
Deno.serve(async (request: Request) => {
  try {
    return await handleRequest(request);
  } catch {
    const reference = crypto.randomUUID();
    console.error("Student invitation failed; reference:", reference);
    return new Response(JSON.stringify({ message: "Request failed. Contact the administrator.", reference }), {
      status: 500, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }
});
