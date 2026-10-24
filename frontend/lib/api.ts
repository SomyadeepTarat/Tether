export async function api<T>(path:string, body?:unknown):Promise<T> {
  const response = await fetch(`/api${path}`, {method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)}),cache:'no-store'});
  if(!response.ok){
    const error=await response.json().catch(()=>({detail:'Backend unavailable. Check that FastAPI is running.'}));
    throw new Error(typeof error.detail==='string'?error.detail:`Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}
