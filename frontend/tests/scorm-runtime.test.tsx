import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { resolve } from "node:path";

function runtime(status = 200) {
  const messages: string[] = [];
  class Xhr {
    status = status;
    open() {}
    setRequestHeader() {}
    send(value: string) {
      messages.push(value);
    }
  }
  const context = {
    window: {} as Record<string, Record<string, (...args: string[]) => string>>,
    XMLHttpRequest: Xhr,
  };
  const source = readFileSync(
    resolve(process.cwd(), "../backend/app/assets/player.js"),
    "utf8",
  ).replace(
    "__ELOR_CONFIG__",
    JSON.stringify({
      id: "learner",
      url: "/scoped/runtime",
      state: { "cmi.suspend_data": "bookmark" },
    }),
  );
  vm.runInNewContext(source, context);
  return {
    api: context.window.API,
    modern: context.window.API_1484_11,
    messages,
  };
}
describe("SCORM preview runtime", () => {
  it("requires initialization, resumes state and persists commits", () => {
    const { api, messages } = runtime();
    expect(api.LMSCommit("")).toBe("false");
    expect(api.LMSGetLastError()).toBe("301");
    expect(api.LMSInitialize("")).toBe("true");
    expect(api.LMSGetValue("cmi.suspend_data")).toBe("bookmark");
    expect(api.LMSSetValue("cmi.core.lesson_status", "completed")).toBe("true");
    expect(api.LMSCommit("")).toBe("true");
    expect(JSON.parse(messages[0])["cmi.core.lesson_status"]).toBe("completed");
  });
  it("reports persistence failures rather than pretending they saved", () => {
    const { modern } = runtime(503);
    modern.Initialize("");
    expect(modern.Terminate("")).toBe("false");
    expect(modern.GetLastError()).toBe("101");
  });
});
