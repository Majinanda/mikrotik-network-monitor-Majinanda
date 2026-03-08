const themeToggle = document.getElementById('theme-toggle');
const themeIcon = document.getElementById('theme-icon');

function initTheme() {
    if (localStorage.getItem('theme') === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.classList.add('dark');
        themeIcon.classList.remove('fa-moon');
        themeIcon.classList.add('fa-sun');
    }
}

themeToggle.addEventListener('click', () => {
    document.documentElement.classList.toggle('dark');
    if (document.documentElement.classList.contains('dark')) {
        localStorage.setItem('theme', 'dark');
        themeIcon.classList.remove('fa-moon');
        themeIcon.classList.add('fa-sun');
    } else {
        localStorage.setItem('theme', 'light');
        themeIcon.classList.remove('fa-sun');
        themeIcon.classList.add('fa-moon');
    }
});

initTheme();

// Redirect if already logged in
if (localStorage.getItem('dashboard_token')) {
    window.location.href = '/';
}

const loginForm = document.getElementById('login-form');
const errorMessage = document.getElementById('error-message');
const errorText = document.getElementById('error-text');
const submitBtn = document.getElementById('submit-btn');

loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    errorMessage.classList.add('hidden');
    
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    
    const formData = new URLSearchParams();
    formData.append('username', email); // OAuth2 expects 'username' field
    formData.append('password', password);

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    try {
        const response = await fetch('/api/auth/token', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            localStorage.setItem('dashboard_token', data.access_token);
            localStorage.setItem('user_role', data.role);
            window.location.href = '/';
        } else {
            throw new Error(data.detail || 'Login failed');
        }
    } catch (error) {
        errorMessage.classList.remove('hidden');
        errorText.textContent = error.message;
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<span>Sign In</span><i class="fas fa-arrow-right ml-2"></i>';
    }
});
