(function () {
  const config = __ELOR_CONFIG__;
  const values = Object.assign({
    "cmi.core.lesson_status": "not attempted",
    "cmi.completion_status": "unknown",
    "cmi.core.student_id": config.id,
    "cmi.learner_id": config.id,
    "cmi.core.student_name": "Repository learner",
    "cmi.learner_name": "Repository learner",
  }, config.state);
  let initialized = false;
  let error = "0";
  function commit() {
    if (!initialized) { error = "301"; return "false"; }
    try {
      const request = new XMLHttpRequest();
      request.open("POST", config.url, false);
      request.setRequestHeader("Content-Type", "text/plain");
      request.send(JSON.stringify(values));
      error = request.status >= 200 && request.status < 300 ? "0" : "101";
      return error === "0" ? "true" : "false";
    } catch { error = "101"; return "false"; }
  }
  const api = {
    Initialize: () => { initialized = true; error = "0"; return "true"; },
    Terminate: () => { const result = commit(); if (result === "true") initialized = false; return result; },
    GetValue: key => {
      if (!initialized) { error = "301"; return ""; }
      error = "0";
      return String(values[key] ?? "");
    },
    SetValue: (key, value) => {
      if (!initialized) { error = "301"; return "false"; }
      if (!key.startsWith("cmi.") || String(value).length > 32768) { error = "201"; return "false"; }
      values[key] = String(value); error = "0"; return "true";
    },
    Commit: commit,
    GetLastError: () => error,
    GetErrorString: code => code === "0" ? "No error" : "Preview runtime error",
    GetDiagnostic: () => error,
  };
  window.API_1484_11 = api;
  window.API = {
    LMSInitialize: api.Initialize, LMSFinish: api.Terminate,
    LMSGetValue: api.GetValue, LMSSetValue: api.SetValue, LMSCommit: api.Commit,
    LMSGetLastError: api.GetLastError, LMSGetErrorString: api.GetErrorString,
    LMSGetDiagnostic: api.GetDiagnostic,
  };
})();
