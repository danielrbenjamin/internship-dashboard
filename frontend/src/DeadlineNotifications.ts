import {useEffect, useState} from "react";

type Deadline = {id:number; subject:string; due:string};
const permissionKey = "desk-deadline-notifications";
const hours = 60 * 60 * 1000;

export function useDeadlineNotifications(deadlines:Deadline[], owner:boolean, persistent = true) {
  const [enabled,setEnabled] = useState(()=>persistent && localStorage.getItem(permissionKey)==="enabled");
  useEffect(()=>{
    if(!persistent || !owner || !enabled || !("Notification" in window) || Notification.permission!=="granted")return;
    const check=()=>{
      for(const deadline of deadlines){
        const remaining=Date.parse(deadline.due)-Date.now();
        if(!(remaining>0 && remaining<=24*hours))continue;
        const windowHours=remaining<=3*hours?3:24;
        const key=[permissionKey,deadline.id,deadline.due,windowHours].join(":");
        if(localStorage.getItem(key))continue;
        try{
          new Notification(deadline.subject,{body:"Due "+new Date(deadline.due).toLocaleString(),tag:key});
          localStorage.setItem(key,"sent");
        }catch{
          return;
        }
      }
    };
    check();
    const timer=window.setInterval(check,30000);
    return ()=>window.clearInterval(timer);
  },[deadlines,enabled,owner,persistent]);
  return {
    enabled,supported:"Notification" in window,
    toggle:async()=>{
      if(!persistent){setEnabled(value=>!value);return;}
      if(enabled){
        localStorage.removeItem(permissionKey);
        setEnabled(false);
        return;
      }
      if(await Notification.requestPermission()!=="granted")throw new Error("Enable browser notifications to receive desktop reminders.");
      localStorage.setItem(permissionKey,"enabled");
      setEnabled(true);
    },
  };
}
