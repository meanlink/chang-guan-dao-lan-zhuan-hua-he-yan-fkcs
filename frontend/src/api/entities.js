import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const flowEvents={list:()=>api('/flow-events'),create:data=>api('/flow-events',{method:'POST',body:JSON.stringify(data)})};
export const reviews={list:()=>api('/reviews'),get:id=>api('/reviews/'+id),create:data=>api('/reviews',{method:'POST',body:JSON.stringify(data)}),retry:id=>api('/reviews/'+id+'/retry',{method:'POST'})};
