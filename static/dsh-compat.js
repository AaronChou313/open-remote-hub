/* DSH rc.6 calls randomUUID on HTTP LAN origins where browsers omit it.
   Supply only that missing standard API, using the browser's secure RNG. */
(()=>{
 const c=globalThis.crypto;
 if(c&&typeof c.randomUUID!=='function'&&typeof c.getRandomValues==='function'){
  Object.defineProperty(c,'randomUUID',{configurable:true,value:()=>{
   const data=c.getRandomValues(new Uint8Array(16));data[6]=(data[6]&15)|64;data[8]=(data[8]&63)|128;
   const h=Array.from(data,b=>b.toString(16).padStart(2,'0')).join('');
   return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
  }});
 }
})();
