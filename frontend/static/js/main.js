// Camera handling
function initCamera(videoElement) {
    if (videoElement) {
        navigator.mediaDevices.getUserMedia({ video: true })
            .then(stream => {
                videoElement.srcObject = stream;
            })
            .catch(err => {
                console.error('Error accessing camera:', err);
                alert('Error accessing camera. Please make sure you have granted camera permissions.');
            });
    }
}

// Stop camera stream
function stopCamera(videoElement) {
    if (videoElement && videoElement.srcObject) {
        const stream = videoElement.srcObject;
        const tracks = stream.getTracks();
        tracks.forEach(track => track.stop());
        videoElement.srcObject = null;
    }
}

// Handle voter registration form
document.addEventListener('DOMContentLoaded', function() {
    const registrationForm = document.getElementById('voter-registration-form');
    const videoElement = document.getElementById('camera-preview');

    if (videoElement) {
        initCamera(videoElement);
    }

    if (registrationForm) {
        registrationForm.addEventListener('submit', function(e) {
            const loadingSpinner = document.querySelector('.loading-spinner');
            if (loadingSpinner) {
                loadingSpinner.style.display = 'block';
            }
        });
    }
});

// Handle voting verification
document.addEventListener('DOMContentLoaded', function() {
    const verificationForm = document.getElementById('voter-verification-form');
    const videoElement = document.getElementById('verification-camera');

    if (videoElement) {
        initCamera(videoElement);
    }

    if (verificationForm) {
        verificationForm.addEventListener('submit', function(e) {
            const loadingSpinner = document.querySelector('.loading-spinner');
            if (loadingSpinner) {
                loadingSpinner.style.display = 'block';
            }
        });
    }
});

// Handle voting form submission
document.addEventListener('DOMContentLoaded', function() {
    const votingForm = document.getElementById('voting-form');
    
    if (votingForm) {
        votingForm.addEventListener('submit', function(e) {
            const selectedCandidate = document.querySelector('input[name="candidate"]:checked');
            if (!selectedCandidate) {
                e.preventDefault();
                alert('Please select a candidate to vote.');
            } else {
                const confirmed = confirm('Are you sure you want to cast your vote? This action cannot be undone.');
                if (!confirmed) {
                    e.preventDefault();
                }
            }
        });
    }
});

// Handle 2FA form
document.addEventListener('DOMContentLoaded', function() {
    const twoFactorForm = document.getElementById('two-factor-form');
    
    if (twoFactorForm) {
        const codeInput = document.getElementById('2fa-code');
        if (codeInput) {
            codeInput.addEventListener('input', function() {
                this.value = this.value.replace(/[^0-9]/g, '');
                if (this.value.length > 6) {
                    this.value = this.value.slice(0, 6);
                }
            });
        }
    }
});

// Auto-dismiss alerts
document.addEventListener('DOMContentLoaded', function() {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            const closeButton = alert.querySelector('.btn-close');
            if (closeButton) {
                closeButton.click();
            }
        }, 5000);
    });
}); 