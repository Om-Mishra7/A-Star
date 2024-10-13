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

    // Encode the code in Base64
    const encodedCode = encodeBase64(code);

    // Prepare the request payload
    const payload = {
      problem_id: problemId,
      code: encodedCode,
      language: selectedLanguage
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
        throw new Error('Network response was not ok');
      }
      return response.json();
    })
    .then(data => {
      // Use the returned submission_id for polling
      const submissionId = data.submission_id;
      pollSubmission(submissionId);  // Pass submission_id to polling
    })
    .catch(error => {
      console.error('Error:', error);
      document.getElementById('output').innerText = 'Error submitting code.';
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

          if (data.data.stderr) {
            const stderr = data.data.stderr;
            document.getElementById('output').classList.add('incorrect-answer');
            document.getElementById('output').innerHTML = `<div class="result">Status: ${result}</div><div class="time">Time: ${time}</div><div class="memory">Memory: ${memory}</div><div class="error">Error: ${stderr}</div>`;
          }
          else if (result === 'Accepted') {
            document.getElementById('output').classList.add('correct-answer');
            document.getElementById('output').innerHTML = `<div class="result">Status: ${result}</div><div class="time">Time: ${time}</div><div class="memory">Memory: ${memory}</div>`; 
          }
          else {
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
        document.getElementById('output').innerText = 'Error fetching submission status.';
        clearInterval(pollInterval);  // Stop polling on error
      });
    }, 2000);
  }

  function encodeBase64(str) {
    return btoa(unescape(encodeURIComponent(str)));
  }
});
