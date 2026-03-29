export async function POST() {
  const backendBase = process.env.BACKEND_API_URL || 'http://127.0.0.1:3201';
  const url = new URL(`${backendBase}/test/trigger`);

  try {
    const response = await fetch(url.toString(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      return new Response('Error triggering test event', { status: response.status });
    }

    const data = await response.json();
    return new Response(JSON.stringify(data), {
      headers: { 'Content-Type': 'application/json' },
      status: 200,
    });
  } catch (err: any) {
    console.error('Trigger Proxy Error:', err);
    return new Response('Internal Server Error', { status: 500 });
  }
}
