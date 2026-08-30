function postAjax(url, formData) {
  return fetch(url, {
    method: 'POST',
    headers: { 'X-Requested-With': 'fetch' },
    body: formData,
  });
}
