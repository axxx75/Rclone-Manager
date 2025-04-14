document.addEventListener('DOMContentLoaded', function() {
    // Enable all tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    });
    
    // Auto-refresh for active jobs page
    if (document.querySelector('.active-jobs-table')) {
        setInterval(function() {
            location.reload();
        }, 30000); // Refresh every 30 seconds
    }
    
    // Confirm job deletion
    document.querySelectorAll('.confirm-action').forEach(element => {
        element.addEventListener('click', function(e) {
            if (!confirm(this.getAttribute('data-confirm-message') || 'Are you sure?')) {
                e.preventDefault();
                return false;
            }
        });
    });
    
    // Handle form submission with validation
    document.querySelectorAll('form.needs-validation').forEach(form => {
        form.addEventListener('submit', function(e) {
            if (!form.checkValidity()) {
                e.preventDefault();
                e.stopPropagation();
            }
            form.classList.add('was-validated');
        });
    });
});
