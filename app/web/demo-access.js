(() => {
  const nativeFetch = window.fetch.bind(window);
  let accessPromise;

  async function ensureDemoAccess() {
    const statusResponse = await nativeFetch('/api/access');
    if (!statusResponse.ok) throw new Error('Could not check demo access. Reload and try again.');
    const status = await statusResponse.json();
    if (!status.required || status.authenticated) return;

    for (let attempt = 0; attempt < 3; attempt += 1) {
      const code = window.prompt('Enter the demo access code provided with this submission:');
      if (code === null) throw new Error('Demo access code is required.');
      const response = await nativeFetch('/api/access', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      if (response.ok) return;
      window.alert('That demo access code was not accepted.');
    }
    throw new Error('Too many incorrect demo access codes. Reload to try again.');
  }

  window.fetch = async (input, init) => {
    const requestUrl = input instanceof Request ? input.url : String(input);
    const url = new URL(requestUrl, window.location.href);
    if (url.origin === window.location.origin && url.pathname.startsWith('/api/') && url.pathname !== '/api/access') {
      if (!accessPromise) accessPromise = ensureDemoAccess();
      await accessPromise;
    }
    return nativeFetch(input, init);
  };
})();
