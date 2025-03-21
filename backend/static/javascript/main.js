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
            // Safe check for university_details and university roll number
            if (data.university_details === undefined || data.university_details.university_roll_number === undefined) {
                // Show the modal if the university roll number is missing
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
                        <label for="universityRollNumber">University Roll Number:</label>
                        <input type="text" id="universityRollNumber" name="universityRollNumber" required />
                    </div>
                    <div>
                        <label for="profilePicture">Profile Picture (Your Face):</label>
                        <input type="file" id="profilePicture" name="profilePicture" accept="image/*" required />
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
            background-color: #fff;
            padding: 20px;
            border-radius: 8px;
            width: 400px;
            max-width: 100%;
            text-align: center;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
        }

        h2 {
            margin-bottom: 20px;
            font-size: 24px;
            font-family: 'Arial', sans-serif;
            text-align: left;
        }

        label {
            font-size: 16px;
            margin-bottom: 8px;
            display: block;
            text-align: left;
        }

        input[type="text"],
        input[type="file"] {
            width: 100%;
            padding: 8px;
            margin-bottom: 15px;
            border: 1px solid #ccc;
            border-radius: 5px;
            box-sizing: border-box;
        }

        button {
            background-color: #004085;
            color: white;
            padding: 10px 15px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
            width: 100%;
        }

        button[type="submit"]:hover {
            background-color: #0056b3;
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

        const universityRollNumber = document.getElementById('universityRollNumber').value;
        const profilePicture = document.getElementById('profilePicture').files[0];

        if (!universityRollNumber || !profilePicture) {
            alert("Please fill in all the fields before submitting.");
            return;
        }

        // Create FormData for the submission
        let formData = new FormData();
        formData.append('universityRollNumber', universityRollNumber);
        formData.append('profilePicture', profilePicture);

        // Send the data to the server
        fetch('/api/v1/user/university-details', {
            method: 'POST',
            body: formData,
        }).then((response) => {
            if (response.ok) {
                // Close the modal after successful submission
                modal.style.display = 'none';
                document.body.classList.remove('modal-open');
            } else {
                alert('There was an issue submitting your profile details. Please try again.');
            }
        }).catch((error) => {
            console.error('Error:', error);
            alert('An error occurred. Please try again later.');
        });
    });
}
