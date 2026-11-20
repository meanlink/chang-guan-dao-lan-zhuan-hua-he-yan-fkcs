/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{id:number,flow_no:string,zone:string,business_date:string,event_type:string,visitors:number,received_at:number,note:string}} FlowEvent */
/** @typedef {{id:number,name:string,business_date:string,zone:string,as_of_then:number,as_of_now:number,status:string,progress:number,cursor:number,sample_size:number,result:Object,error:string}} Review */
export {};
