document.onreadystatechange = function () {
    if (document.readyState === 'complete') {
        console.log('Hey there developer, welcome to the console. If you are looking for a project to contribute to, email me at: a-star-console@om-mishra.com');
    }

    // Check if user has completed the profile
    fetch('/api/v1/user', {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
        },
    })
        .then((response) => response.json())
        .then((data) => {
            // Safe check for university_details and student_id
            if (data.university_details === undefined || data.university_details.student_id === undefined) {
                // Show the modal if student ID is missing
                showModal();
            }
        })
        .catch((error) => {
            console.error('Error:', error);
        });
};

function showModal() {
    // Create and append the modal HTML dynamically
    const modalHTML = `
        <div id="studentModal" class="modal">
            <div class="modal-content">
                <h2>Complete Your Profile</h2>
                <form id="studentForm">
                    <div>
                        <label for="studentId">Student ID:</label>
                        <input type="text" id="studentId" name="studentId" required />
                    </div>
                    <div>
                        <label for="studentPhoto">Upload Photo:</label>
                        <input type="file" id="studentPhoto" name="studentPhoto" accept="image/*" required />
                    </div>
                    <button type="submit">Submit</button>
                </form>
            </div>
        </div>
    `;

    // Append modal HTML to the body
    document.body.insertAdjacentHTML('beforeend', modalHTML);

    // Dynamically add styles
    const style = document.createElement('style');
    style.innerHTML = `
        /* Modal Styles */
        .modal {
            display: flex;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.5);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }

        /* Modal content */
        .modal-content {
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            width: 400px;
            text-align: center;
        }

        button {
            margin-top: 10px;
        }

        /* Disable scrolling when the modal is open */
        body.modal-open {
            overflow: hidden;
        }
    `;
    document.head.appendChild(style);

    // Show the modal and prevent scrolling
    const modal = document.getElementById('studentModal');
    modal.style.display = 'flex';
    document.body.classList.add('modal-open');

    // Handle form submission
    const form = document.getElementById('studentForm');
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        const studentId = document.getElementById('studentId').value;
        const studentPhoto = document.getElementById('studentPhoto').files[0];

        // Process the form data (e.g., send to API)
        console.log('Student ID:', studentId);
        console.log('Photo:', studentPhoto);

        // Here you could send the data to the backend, e.g., using fetch()

        // Hide the modal after submission (for demo purposes)
        modal.style.display = 'none';
        document.body.classList.remove('modal-open');
    });

    // Close modal event handler
    const closeModalButton = document.getElementById('closeModal');
    closeModalButton.addEventListener('click', function () {
        modal.style.display = 'none';
        document.body.classList.remove('modal-open');
    });
}
