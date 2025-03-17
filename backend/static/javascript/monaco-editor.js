// Disable copy, cut, and paste
["copy", "cut", "paste"].forEach((event) =>
  document.addEventListener(event, (e) => e.preventDefault())
);

// Keystroke and focus tracking
let keyStrokes = [];
let focusEvents = [];
let focusLostTime = null;

document.addEventListener("keydown", (e) => {
  if (document.hasFocus()) {
    keyStrokes.push({ key: e.key, timestamp: new Date().toISOString() });
  }
});

window.addEventListener("blur", () => {
  focusLostTime = new Date();
});

window.addEventListener("focus", () => {
  if (focusLostTime) {
    focusEvents.push({
      focusIn: new Date().toISOString(),
      focusOut: focusLostTime.toISOString(),
    });
    focusLostTime = null;
  }
});

// Monaco Editor Setup
require(["vs/editor/editor.main"], function () {
  const editor = monaco.editor.create(
    document.getElementById("monaco-editor"),
    {
      language: "python",
      theme: "vs-dark",
      automaticLayout: true,
      minimap: { enabled: false },
      lineNumbers: "on",
      folding: true,
      scrollBeyondLastLine: false,
      renderLineHighlight: "none",
      hideCursorInOverviewRuler: true,
      overviewRulerBorder: false,
      suggestOnTriggerCharacters: true,
      quickSuggestions: { other: true, comments: true, strings: true },
    }
  );

  // Change language
  document.getElementById("language").addEventListener("change", function () {
    monaco.editor.setModelLanguage(editor.getModel(), this.value);
  });

  // Change theme
  document
    .getElementById("theme-select")
    .addEventListener("change", function () {
      monaco.editor.setTheme(this.value);
    });

  // Submit code
  document.getElementById("submit").addEventListener("click", function () {
    this.disabled = true;
    document.getElementById("output").innerText = "Submitting code...";
    const code = editor.getValue();
    const problemId = document.getElementById("problem-id").value;
    const selectedLanguage = document.getElementById("language").value;

    if (!code.trim()) {
      document.getElementById("output").innerText =
        "Editor is empty. Write code before submitting.";
      this.disabled = false;
      return;
    }

    fetch("/api/v1/submissions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        problem_id: problemId,
        code: btoa(unescape(encodeURIComponent(code))),
        language: selectedLanguage,
        key_strokes: keyStrokes,
        focus_events: focusEvents,
      }),
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.response_code == "429") {
          document.getElementById("output").innerText = `${data.message}`;
          this.disabled = false;
          return;
        }
        document.getElementById(
          "output"
        ).innerText = `Submission successful. Polling for results...`;
        pollSubmission(data.submission_id);
      })
      .catch((error) => {
        document.getElementById("output").innerText = "Submission failed.";
        this.disabled = false;
      });
  });

  function pollSubmission(submissionId) {
    const pollInterval = setInterval(() => {
      fetch(`/api/v1/submissions/${submissionId}`)
        .then((response) => response.json())
        .then((data) => {
          if (data.data.status.id !== 0) {
            clearInterval(pollInterval);
            document.getElementById("submit").disabled = false;
            document.getElementById(
              "output"
            ).innerHTML = `<p> Status: ${data.data.status.description} | Time: ${data.data.time}'s | Memory: ${data.data.memory}'KB</p><p>Stdout: ${data.data.stdout}</p><p>Stderr: ${data.data.stderr}</p>`;
            document.getElementById("submit").disabled = true;
            setTimeout(() => {
              document.getElementById("submit").disabled = false;
            }, 10000);
          }
        })
        .catch(() => {
          document.getElementById("output").innerText =
            "Error fetching submission status.";
          clearInterval(pollInterval);
        });
    }, 2000);
  }
});

// Mobile detection
function checkMobile() {
  if (window.innerWidth < 768) {
    document.body.innerHTML =
      "<h1 style='text-align: center; padding: 50px;'>Use a desktop device to view this page.</h1>";
  }
}
checkMobile();
window.addEventListener("resize", checkMobile);
