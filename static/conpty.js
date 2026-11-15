'use strict';
const sessionName = decodeURIComponent(location.pathname.split('/').pop());
const terminal = new Terminal({cursorBlink:true, convertEol:false, fontSize:14, scrollback:10000, theme:{background:'#101114'}});
const container = document.querySelector('#terminal');
const status = document.querySelector('#terminalStatus');
document.querySelector('#terminalName').textContent = sessionName + ' · PowerShell';
terminal.open(container);
let socket;
function resize() {
  const cell = terminal._core?._renderService?.dimensions?.css?.cell;
  if (!cell?.width || !cell?.height) return;
  const cols = Math.max(2, Math.floor(container.clientWidth / cell.width) - 2);
  const rows = Math.max(1, Math.floor(container.clientHeight / cell.height) - 1);
  terminal.resize(cols, rows);
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type:'resize', cols, rows}));
}
function connect() {
  if (socket) { socket.onclose = null; socket.close(); }
  terminal.reset();
  status.textContent = '正在连接';
  const connection = new WebSocket(location.origin.replace(/^http/, 'ws') + '/terminal/conpty-ws/' + encodeURIComponent(sessionName));
  socket = connection;
  connection.onopen = () => { status.textContent = '已连接'; resize(); terminal.focus(); };
  connection.onmessage = event => terminal.write(event.data);
  connection.onclose = () => { status.textContent = '连接已关闭，后台会话保留'; };
  connection.onerror = () => { status.textContent = '终端不可达，请检查登录与后台服务'; };
}
terminal.onData(data => { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type:'input', data})); });
new ResizeObserver(resize).observe(container);
document.querySelector('#reconnect').onclick = connect;
connect();
