(function () {
  const config = __ELOR_CONFIG__;
  const container = document.getElementById("h5p");
  const options = {
    h5pJsonPath: config.base.replace(/\/$/, ""),
    frameJs: config.runtime + "frame.bundle.js",
    frameCss: config.runtime + "styles/h5p.css",
    contentUserData: config.state ? [{dataType: "state", previousState: JSON.stringify(config.state)}] : [],
  };
  function save(value) {
    return fetch(config.base + "__runtime", {
      method: "POST", headers: {"Content-Type": "text/plain"}, body: JSON.stringify(value),
    });
  }
  new H5PStandalone.H5P(container, options).then(() => {
    if (window.H5P) {
      H5P.externalDispatcher.on("xAPI", event => save({"h5p.last_statement": event.data.statement}));
      setInterval(() => {
        const instance = H5P.instances && H5P.instances[0];
        if (instance && instance.getCurrentState) save({"h5p.state": instance.getCurrentState()});
      }, 10000);
    }
  }).catch(error => {
    container.textContent = "Cannot play this H5P package: " + error.message;
  });
})();
