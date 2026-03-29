export async function GET(request: Request) {
  const backendBase = process.env.BACKEND_API_URL || 'http://127.0.0.1:3201';
  const url = new URL(`${backendBase}/events`);
  // Pass through query params if needed
  url.search = new URL(request.url).search;

  try {
    const response = await fetch(url.toString(), {
      method: 'GET',
      headers: {
        'Accept': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
    });

    if (!response.ok) {
      return new Response('Error connecting to Orchestrator', { status: response.status });
    }

    // Proxy the stream
    return new Response(response.body, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
      status: 200,
    });
  } catch (err: any) {
    console.error('SSE Proxy Error:', err);
    return new Response('Internal Server Error', { status: 500 });
  }
}
