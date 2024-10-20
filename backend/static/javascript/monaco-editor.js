// Prevent copy, cut, and paste actions
document.addEventListener('copy', (e) => {
  e.preventDefault();
});

document.addEventListener('cut', (e) => {
  e.preventDefault();
});

document.addEventListener('paste', (e) => {
  e.preventDefault();
});

// Array to track key strokes and focus events
let keyStrokes = [];
let focusEvents = [];
let focusLostTime = null;

// Track key strokes
document.addEventListener('keydown', (e) => {
  if (document.hasFocus()) {
    keyStrokes.push({ key: e.key, timestamp: new Date().toISOString() });
  }
});

// Store the time when the window loses focus and record the focusOut event
window.addEventListener('blur', () => {
  focusLostTime = new Date();
});

// When the window gains focus again, record the focusIn event
window.addEventListener('focus', () => {
  if (focusLostTime) {
    const regainedFocusTime = new Date();

    // Push focus event object with both focusIn and focusOut times
    focusEvents.push({
      focusIn: regainedFocusTime.toISOString(),
      focusOut: focusLostTime.toISOString()
    });

    console.log('Focus regained:', regainedFocusTime.toISOString());
    console.log('Focus lost at:', focusLostTime.toISOString());

    // Reset lost focus time
    focusLostTime = null;
  }
});

// Monaco Editor Setup
require.config({ paths: { 'vs': 'https://unpkg.com/monaco-editor@0.26.1/min/vs' } });

let proxy = URL.createObjectURL(new Blob([`
  self.MonacoEnvironment = {
    baseUrl: 'https://unpkg.com/monaco-editor@0.26.1/min/'
  };
  importScripts('https://unpkg.com/monaco-editor@0.26.1/min/vs/base/worker/workerMain.js');
`], { type: 'text/javascript' }));

window.MonacoEnvironment = { getWorkerUrl: () => proxy };

require(["vs/editor/editor.main"], function () {
  const editor = monaco.editor.create(document.getElementById('monaco-editor'), {
    language: 'python',
    theme: 'vs-dark',
    automaticLayout: true,
    minimap: { enabled: false },
    lineNumbers: 'on',
    folding: false,
    scrollBeyondLastLine: false,
    renderLineHighlight: 'none',
    hideCursorInOverviewRuler: true,
    overviewRulerBorder: false
  });

  // Change language functionality
  document.getElementById('language').addEventListener('change', function () {
    monaco.editor.setModelLanguage(editor.getModel(), this.value);
  });

  // Change theme functionality based on dropdown
  document.getElementById('theme-select').addEventListener('change', function () {
    let selectedTheme = this.value;
    monaco.editor.setTheme(selectedTheme);
  });

  // Submit button functionality
  document.getElementById('submit').addEventListener('click', function () {
    document.getElementById('submit').disabled = true;
    document.getElementById('output').innerText = 'Submitting code...';
    const code = editor.getValue();
    const problemId = document.getElementById('problem-id').value;
    const selectedLanguage = document.getElementById('language').value;

    if (!code) {
      document.getElementById('output').innerText = 'The code editor is empty, please write some code before submitting.';
      return;
    }

    // Encode the code in Base64
    const encodedCode = encodeBase64(code);

    // Prepare the request payload
    const payload = {
      problem_id: problemId,
      code: encodedCode,
      language: selectedLanguage,
      key_strokes: keyStrokes, // Add key strokes to the payload
      focus_events: focusEvents // Add focus events to the payload
    };

    // Send POST request to the API
    fetch('/api/v1/submissions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload)
    })
    .then(response => {
      if (!response.ok) {
        if (response.status === 400) {
          throw new Error('The code editor is empty, please write some code before submitting.');
        }
      }
      return response.json();
    })
    .then(data => {
      // Use the returned submission_id for polling
      const submissionId = data.submission_id;
      pollSubmission(submissionId);  // Pass submission_id to polling
    })
    .catch(error => {
      document.getElementById('submit').disabled = false;
      console.error('Error:', error);
      document.getElementById('output').innerText = error.message;
    });
  });

  // Polling system for submission status
  function pollSubmission(submissionId) {
    const pollInterval = setInterval(function checkStatus() {
      fetch(`/api/v1/submissions/${submissionId}`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      })
      .then(response => {
        if (!response.ok) {
          throw new Error('Failed to fetch submission status');
        }
        return response.json();
      })
      .then(data => {
        document.getElementById('output').innerText = 'Polling result: In progress...';
        const statusId = data.data.status.id;
        if (statusId !== 0) {
          // Final status, display results
          document.getElementById('submit').disabled = false;
          const time = data.data.time + " seconds";
          const memory = data.data.memory + " KB";
          const result = data.data.status.description;

          if (time === null) {
            time = "N/A";
          }

          if (memory === null) {
            memory = "N/A";
          } 

          if (data.data.number_of_passed_test_cases === undefined) {
            data.data.number_of_passed_test_cases = "N/A";
          }

          if (data.data.stderr) {
            const stderr = data.data.stderr;
            document.getElementById('output').classList.remove('correct-answer');
            document.getElementById('output').classList.add('incorrect-answer');
            document.getElementById('output').innerHTML = `<div class="result">Status: ${result}</div><div class="time">Time: ${time}</div><div class="memory">Memory: ${memory}</div><div class="error">Error: ${stderr}</div><div class="number_of_passed_test_cases">Number of passed test cases: ${data.data.number_of_passed_test_cases}</div>`;
          } else if (result === 'Accepted') {
            document.getElementById('output').classList.remove('incorrect-answer');
            document.getElementById('output').classList.add('correct-answer');
            document.getElementById('output').innerHTML = `<div class="result">Status: ${result}</div><div class="time">Time: ${time}</div><div class="memory">Memory: ${memory}</div>`; 
          } else {
            document.getElementById('output').classList.remove('correct-answer');
            document.getElementById('output').classList.add('incorrect-answer');
            document.getElementById('output').innerHTML = `<div class="result">Status: ${result}</div><div class="time">Time: ${time}</div><div class="memory">Memory: ${memory}</div><div class="number_of_passed_test_cases">Number of passed test cases: ${data.data.number_of_passed_test_cases}</div>`;
          }
          clearInterval(pollInterval);  // Stop polling
        } else {
          document.getElementById('output').innerText = 'Polling result: In progress...';
        }
      })
      .catch(error => {
        console.error('Error:', error);
        document.getElementById('submit').disabled = false;
        document.getElementById('output').innerText = 'Error fetching submission status.';
        clearInterval(pollInterval);  // Stop polling on error
      });
    }, 2000);
  }

  function encodeBase64(str) {
    return btoa(unescape(encodeURIComponent(str)));
  }
});
