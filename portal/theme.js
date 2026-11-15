const icon = name => `<svg aria-hidden="true"><use href="./icons.svg#${name}"></use></svg>`;
export function setTheme(dark) {
  document.documentElement.classList.toggle('dark', dark);
  const button=document.querySelector('#theme');
  button.innerHTML=icon(dark?'sun':'moon');
  button.setAttribute('aria-label',dark?'切换为浅色模式':'切换为暗色模式');
}
document.querySelector('#theme').onclick=()=>{
  const dark=!document.documentElement.classList.contains('dark');
  setTheme(dark);
  localStorage.setItem('openremotehub.portal.theme',dark?'dark':'light');
};
