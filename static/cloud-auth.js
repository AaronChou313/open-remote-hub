'use strict';
(async () => {
  const values = new URLSearchParams(location.hash.slice(1));
  history.replaceState(null, '', location.pathname);
  try {
    if (!values.get('ticket')) throw Error('缺少登录凭据，请重新登录。');
    const response = await fetch('/auth/cloud/exchange', {
      method:'POST',headers:{'Content-Type':'application/json','X-ORH-Request':'1'},
      body:JSON.stringify({ticket:values.get('ticket'),state:values.get('state') || ''}),
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.detail || '登录失败，请重试。');
    location.replace('/');
  } catch (error) {
    document.querySelector('#cloudMessage').textContent = error.message;
    document.querySelector('#cloudRetry').hidden = false;
  }
})();
