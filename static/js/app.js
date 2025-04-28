/**
 * RClone Manager - JavaScript Frontend Module
 * 
 * Questo file contiene la logica per:
 * 1. Anelli di progresso per visualizzare lo stato dei job
 * 2. Gestione della pagina dei job attivi con aggiornamenti in tempo reale
 * 3. Sistema di notifiche del browser
 * 4. Utility generali dell'interfaccia
 */

/**
 * Modulo per la gestione degli anelli di progresso
 * Visualizza lo stato dei job in formato grafico con SVG
 */
window.JobProgressRing = {
    /**
     * Crea un anello di progresso per visualizzare lo stato di un job
     * @param {HTMLElement} container - Elemento contenitore
     * @param {string} status - Stato del job (pending, running, completed, error)
     * @param {number} progress - Valore di avanzamento (0-100)
     * @param {string} label - Etichetta da mostrare sotto l'anello
     */
    create: function(container, status, progress = 0, label = '') {
        // Configurazione per i diversi stati
        const statusConfig = {
            'pending': { icon: 'clock', progress: 0 },
            'running': { icon: 'spinner fa-spin', progress: progress || 50 },
            'completed': { icon: 'check', progress: 100 },
            'error': { icon: 'times', progress: 100 }
        };
        
        // Ottieni la configurazione per questo stato
        const config = statusConfig[status] || statusConfig.pending;
        
        // Assicura che il progresso sia un numero tra 0-100
        const progressValue = Math.min(100, Math.max(0, config.progress));
        
        // Crea elemento SVG
        const svgNS = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(svgNS, "svg");
        svg.setAttribute("class", "progress-ring");
        svg.setAttribute("width", "100%");
        svg.setAttribute("height", "100%");
        svg.setAttribute("viewBox", "0 0 36 36");
        
        // Calcola i parametri per il cerchio
        const radius = 15;
        const circumference = 2 * Math.PI * radius;
        const dashoffset = circumference * (1 - progressValue / 100);
        
        // Cerchio di sfondo
        const bgCircle = document.createElementNS(svgNS, "circle");
        bgCircle.setAttribute("class", "progress-ring__circle bg");
        bgCircle.setAttribute("cx", "18");
        bgCircle.setAttribute("cy", "18");
        bgCircle.setAttribute("r", radius.toString());
        bgCircle.setAttribute("stroke-dasharray", circumference.toString());
        bgCircle.setAttribute("stroke-dashoffset", "0");
        
        // Cerchio di progresso
        const progressCircle = document.createElementNS(svgNS, "circle");
        progressCircle.setAttribute("class", `progress-ring__circle ${status}`);
        progressCircle.setAttribute("cx", "18");
        progressCircle.setAttribute("cy", "18");
        progressCircle.setAttribute("r", radius.toString());
        progressCircle.setAttribute("stroke-dasharray", circumference.toString());
        progressCircle.setAttribute("stroke-dashoffset", dashoffset.toString());
        
        // Aggiungi cerchi all'SVG
        svg.appendChild(bgCircle);
        svg.appendChild(progressCircle);
        
        // Crea container per il posizionamento
        const ringContainer = document.createElement("div");
        ringContainer.className = "progress-ring-container";
        
        // Aggiungi icona al centro
        const icon = document.createElement("div");
        icon.className = "progress-ring__icon";
        
        // Per l'icona spinner, aggiungiamo la classe fa-spin per assicurarci che ruoti
        if (config.icon === 'spinner') {
            icon.innerHTML = `<i class="fas fa-${config.icon} fa-spin"></i>`;
        } else {
            icon.innerHTML = `<i class="fas fa-${config.icon}"></i>`;
        }
        
        // Aggiungi SVG e icona al container
        ringContainer.appendChild(svg);
        ringContainer.appendChild(icon);
        
        // Aggiungi etichetta se fornita
        if (label) {
            const statusLabel = document.createElement("div");
            statusLabel.className = "status-label";
            statusLabel.textContent = label;
            container.appendChild(statusLabel);
        }
        
        // Pulisci il container e aggiungi l'anello
        container.innerHTML = '';
        container.appendChild(ringContainer);
    },
    
    /**
     * Aggiorna un anello di progresso esistente
     * @param {HTMLElement} container - Elemento contenitore
     * @param {string} status - Nuovo stato del job
     * @param {number} progress - Nuovo valore di avanzamento
     */
    update: function(container, status, progress = 0) {
        // Se l'elemento ha già un anello, aggiornalo, altrimenti creane uno nuovo
        if (container.querySelector('.progress-ring-container')) {
            const label = container.querySelector('.status-label')?.textContent || '';
            this.create(container, status, progress, label);
        } else {
            this.create(container, status, progress);
        }
    }
};

/**
 * Inizializza la pagina dei job attivi con aggiornamenti in tempo reale
 * Gestisce la visualizzazione della tabella di job attivi e gli aggiornamenti AJAX
 */
function initializeActiveJobsPage() {
    // Elementi DOM
    const activeJobsTable = document.getElementById('active-jobs-table');
    const activeJobsContainer = document.getElementById('active-jobs-container');
    const refreshButton = document.getElementById('refresh-active-jobs');
    const lastUpdateTime = document.getElementById('last-update-time');
    const noJobsMessage = document.getElementById('no-jobs-message');
    
    if (!activeJobsContainer) return; // Non siamo nella pagina index
    
    /**
     * Aggiorna l'orario dell'ultimo aggiornamento
     */
    function updateLastUpdateTime() {
        if (!lastUpdateTime) return;
        const now = new Date();
        lastUpdateTime.textContent = 'Last update: ' + now.toLocaleTimeString();
    }
    
    /**
     * Inizializza i cerchi di progresso per i job esistenti
     */
    function initializeProgressRings() {
        const statusCells = document.querySelectorAll('.job-status-cell');
        statusCells.forEach(cell => {
            const status = cell.getAttribute('data-status') || 'running';
            
            // Calcoliamo un valore per la progressione
            const progress = status === 'running' ? 
                Math.floor(Math.random() * 40) + 50 : // 50-90% per running
                (status === 'completed' ? 100 : 0);   // 100% per completed, 0% per pending/error
            
            JobProgressRing.create(cell, status, progress, status);
        });
    }
    
    /**
     * Recupera e aggiorna la lista dei job attivi tramite API
     */
    function refreshActiveJobs() {
        // Utilizziamo sempre un path relativo per evitare problemi CORS
        fetch('/api/active_jobs')
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok: ' + response.status);
                }
                return response.json();
            })
            .then(data => {
                // Salva i dati per usi futuri
                window.apiData = data;
                
                if (data.active_jobs) {
                    updateActiveJobsTable(data.active_jobs);
                }
                
                // Aggiorna eventuali avvisi di processi non tracciati
                updateUntrackedProcessesWarning(data);
                
                updateLastUpdateTime();
            })
            .catch(error => {
                console.error('Error refreshing active jobs:', error);
                // In caso di errore, aggiorniamo comunque il timestamp
                updateLastUpdateTime();
            });
    }
    
    /**
     * Aggiorna gli avvisi di processi non tracciati
     */
    function updateUntrackedProcessesWarning(data) {
        const untrackedWarning = document.getElementById('untracked-processes-warning');
        const untrackedWarningAlt = document.getElementById('untracked-processes-warning-alt');
        
        if (data.untracked_processes && data.untracked_processes > 0) {
            const warningHtml = `
                <div class="alert alert-warning mt-3" role="alert">
                    <i class="fas fa-exclamation-triangle"></i> 
                    <strong>Attenzione:</strong> Rilevati ${data.untracked_processes} processi rclone attivi sul sistema ma non tracciati dall'applicazione.
                    <a href="/clean_all_jobs" class="alert-link">Esegui pulizia</a> per risolvere eventuali problemi di sincronizzazione.
                </div>
            `;
            
            if (untrackedWarning) {
                untrackedWarning.innerHTML = warningHtml;
                untrackedWarning.style.display = 'block';
            }
            
            if (untrackedWarningAlt && (!data.active_jobs || data.active_jobs.length === 0)) {
                untrackedWarningAlt.innerHTML = warningHtml;
                untrackedWarningAlt.style.display = 'block';
            } else if (untrackedWarningAlt) {
                untrackedWarningAlt.style.display = 'none';
            }
        } else {
            if (untrackedWarning) untrackedWarning.style.display = 'none';
            if (untrackedWarningAlt) untrackedWarningAlt.style.display = 'none';
        }
    }
    
    /**
     * Aggiorna la UI della tabella con i nuovi dati dei job
     * @param {Array} jobs - Lista di job attivi
     */
    function updateActiveJobsTable(jobs) {
        if (!jobs || jobs.length === 0) {
            // Nessun job attivo: mostra anelli di esempio
            if (activeJobsTable) {
                activeJobsTable.closest('.table-responsive').style.display = 'none';
            }
            
            if (!noJobsMessage) {
                const alertDiv = document.createElement('div');
                alertDiv.id = 'no-jobs-message';
                alertDiv.className = 'alert alert-info';
                alertDiv.innerHTML = `
                    <div class="text-center mb-4">
                        <h5>Esempi di anelli di progresso</h5>
                        <div class="d-flex justify-content-center gap-5 my-4">
                            <div class="d-inline-block" id="demo-ring-pending"></div>
                            <div class="d-inline-block" id="demo-ring-running"></div>
                            <div class="d-inline-block" id="demo-ring-completed"></div>
                            <div class="d-inline-block" id="demo-ring-error"></div>
                        </div>
                        <i class="fas fa-info-circle"></i> Nessun job attivo al momento.
                    </div>
                `;
                activeJobsContainer.appendChild(alertDiv);
                
                // Mostra gli anelli di esempio
                setTimeout(() => {
                    JobProgressRing.create(document.getElementById('demo-ring-pending'), 'pending', 0, 'In attesa');
                    JobProgressRing.create(document.getElementById('demo-ring-running'), 'running', 65, 'In corso');
                    JobProgressRing.create(document.getElementById('demo-ring-completed'), 'completed', 100, 'Completato');
                    JobProgressRing.create(document.getElementById('demo-ring-error'), 'error', 85, 'Errore');
                }, 100);
            } else {
                noJobsMessage.style.display = 'block';
            }
            
            return;
        }
        
        // Ci sono job attivi
        if (noJobsMessage) {
            noJobsMessage.style.display = 'none';
        }
        
        // Se la tabella non esiste, creala
        if (!activeJobsTable) {
            createActiveJobsTable(jobs);
            return;
        }
        
        // Assicurati che la tabella sia visibile
        activeJobsTable.closest('.table-responsive').style.display = 'block';
        
        const tbody = activeJobsTable.querySelector('tbody');
        
        // Rimuovi le righe che non corrispondono ai job attivi
        const currentRows = Array.from(tbody.querySelectorAll('tr'));
        currentRows.forEach(row => {
            const source = row.getAttribute('data-source');
            const target = row.getAttribute('data-target');
            
            const jobExists = jobs.some(job => 
                job.source === source && job.target === target);
                
            if (!jobExists) {
                row.remove();
            }
        });
        
        // Aggiorna o aggiungi job
        jobs.forEach(job => {
            const selector = `tr[data-source="${job.source}"][data-target="${job.target}"]`;
            let row = tbody.querySelector(selector);
            
            if (row) {
                // Aggiorna la durata del job esistente
                const durationCell = row.querySelector('.job-duration');
                durationCell.textContent = job.duration_formatted;
            } else {
                // Crea una nuova riga per il job
                row = document.createElement('tr');
                row.setAttribute('data-source', job.source);
                row.setAttribute('data-target', job.target);
                
                if (job.from_scheduler) {
                    row.classList.add('table-primary');
                }
                
                row.innerHTML = `
                    <td class="text-center job-status-cell" data-status="running">
                        <!-- Progress ring will be inserted here via JavaScript -->
                    </td>
                    <td>
                        <code>${job.source}</code>
                        ${job.from_scheduler ? 
                          '<span class="badge bg-primary ms-1" title="Job avviato da pianificazione"><i class="fas fa-calendar-alt"></i> Pianificato</span>' : ''}
                        ${job.recovered ? 
                          '<span class="badge bg-warning ms-1" title="Job recuperato automaticamente"><i class="fas fa-recycle"></i> Recuperato</span>' : ''}
                    </td>
                    <td><code>${job.target}</code></td>
                    <td>${job.start_time}</td>
                    <td class="job-duration">${job.duration_formatted}</td>
                    <td>
                        ${job.dry_run ? 
                         '<span class="badge bg-warning">Dry Run</span>' : 
                         '<span class="badge bg-success">Live</span>'}
                    </td>
                    <td>
                        <div class="btn-group">
                            <button class="btn btn-sm btn-info view-log" data-log-file="${job.log_file}">
                                <i class="fas fa-file-alt"></i> View Log
                            </button>
                            <form action="/cancel_job/-1" method="post" class="d-inline cancel-form">
                                <input type="hidden" name="source" value="${job.source}">
                                <input type="hidden" name="target" value="${job.target}">
                                <button type="submit" class="btn btn-sm btn-danger"
                                        onclick="return confirm('Sei sicuro di voler annullare questo job?');">
                                    <i class="fas fa-times-circle"></i> Cancel
                                </button>
                            </form>
                        </div>
                    </td>
                `;
                
                tbody.appendChild(row);
                
                // Aggiungi event listener per visualizzare i log
                row.querySelector('.view-log').addEventListener('click', function() {
                    const logFile = this.getAttribute('data-log-file');
                    showLogModal(logFile);
                });
            }
            
            // Aggiorna il cerchio di progresso
            const statusCell = row.querySelector('.job-status-cell');
            if (statusCell) {
                const status = 'running'; // Tutti i job attivi sono 'running'
                
                // Assicuriamoci che l'attributo data-status sia impostato correttamente
                statusCell.setAttribute('data-status', status);
                
                // Calcola un progresso basato sulla durata
                let progress = 0;
                if (job.duration < 60) {
                    // Se meno di un minuto, progresso 50-60%
                    progress = 50 + (job.duration / 60 * 10);
                } else if (job.duration < 3600) {
                    // Se meno di un'ora, progresso 60-80%
                    progress = 60 + (job.duration / 3600 * 20);
                } else {
                    // Se più di un'ora, progresso 80-90%
                    progress = 80 + Math.min(10, job.duration / 7200 * 10);
                }
                
                // Aggiorna il cerchio di progresso con animazione
                JobProgressRing.update(statusCell, status, progress);
            }
        });
        
        // Inizializza i cerchi di progresso per le nuove righe
        initializeProgressRings();
    }
    
    /**
     * Mostra una modale con il contenuto del file di log
     * @param {string} logFile - Percorso del file di log
     */
    function showLogModal(logFile) {
        const logContent = document.getElementById('logContent');
        const logModal = new bootstrap.Modal(document.getElementById('logModal'));
        
        // Mostra la modale con un messaggio di caricamento
        logContent.textContent = 'Loading log...';
        logModal.show();
        
        // Ottieni il nome del file log dalla path completa
        const logFileName = logFile.split('/').pop();
        
        // Carica il contenuto del log
        fetch(`/logs/${logFileName}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Failed to load log file');
                }
                return response.text();
            })
            .then(data => {
                logContent.textContent = data;
            })
            .catch(error => {
                logContent.textContent = `Error loading log: ${error.message}`;
            });
    }
    
    /**
     * Crea la tabella dei job attivi da zero
     * @param {Array} jobs - Lista di job attivi
     */
    function createActiveJobsTable(jobs) {
        const tableResponsive = document.createElement('div');
        tableResponsive.className = 'table-responsive';
        
        const table = document.createElement('table');
        table.id = 'active-jobs-table';
        table.className = 'table table-hover';
        
        table.innerHTML = `
            <thead>
                <tr>
                    <th>Status</th>
                    <th>Source</th>
                    <th>Target</th>
                    <th>Started</th>
                    <th>Duration</th>
                    <th>Dry Run</th>
                    <th>Log</th>
                </tr>
            </thead>
            <tbody></tbody>
        `;
        
        tableResponsive.appendChild(table);
        activeJobsContainer.innerHTML = '';
        activeJobsContainer.appendChild(tableResponsive);
        
        // Aggiorna la tabella con i job
        updateActiveJobsTable(jobs);
    }
    
    // Inizializzazione e configurazione
    
    // Pulsante di aggiornamento manuale
    if (refreshButton) {
        refreshButton.addEventListener('click', refreshActiveJobs);
    }
    
    // Setup iniziale
    initializeProgressRings();
    refreshActiveJobs();
    
    // Aggiornamento automatico
    const autoRefreshInterval = setInterval(refreshActiveJobs, 15000);
    
    // Pulizia risorse
    window.addEventListener('beforeunload', function() {
        clearInterval(autoRefreshInterval);
    });
}

/**
 * Sistema di notifiche del browser
 * Gestisce le notifiche push del browser e l'interfaccia delle notifiche
 */
function initNotificationSystem() {
    const notificationBadge = document.getElementById('notificationBadge');
    const notificationsList = document.getElementById('notifications-list');
    const markAllReadBtn = document.getElementById('markAllReadBtn');
    let notificationsEnabled = false;
    let unreadCount = 0;
    
    /**
     * Richiede il permesso per le notifiche del browser
     */
    function requestNotificationPermission() {
        if (!("Notification" in window)) {
            console.log("Questo browser non supporta le notifiche desktop");
            return;
        }
        
        if (Notification.permission !== "granted" && Notification.permission !== "denied") {
            Notification.requestPermission();
        }
    }
    
    /**
     * Carica le notifiche dal server
     */
    function loadNotifications() {
        if (!notificationsList) return;
        
        fetch('/api/notifications?limit=10')
            .then(response => response.json())
            .then(data => {
                notificationsEnabled = data.settings.notifications_enabled;
                unreadCount = data.unread_count;
                updateNotificationBadge();
                renderNotifications(data.notifications);
            })
            .catch(error => {
                console.error('Errore nel caricamento delle notifiche:', error);
                notificationsList.innerHTML = `
                    <div class="text-center p-3 text-muted">
                        <i class="fas fa-exclamation-circle"></i> Errore nel caricamento delle notifiche
                    </div>
                `;
            });
    }
    
    /**
     * Aggiorna il badge con il conteggio delle notifiche non lette
     */
    function updateNotificationBadge() {
        if (!notificationBadge) return;
        
        if (unreadCount > 0) {
            notificationBadge.textContent = unreadCount > 99 ? '99+' : unreadCount;
            notificationBadge.style.display = 'inline-block';
        } else {
            notificationBadge.style.display = 'none';
        }
    }
    
    /**
     * Invia una notifica al browser
     * @param {string} title - Titolo della notifica
     * @param {string} message - Messaggio della notifica
     */
    function sendBrowserNotification(title, message) {
        if (!notificationsEnabled) return;
        if (Notification.permission !== "granted") return;
        
        const notification = new Notification(title, {
            body: message,
            icon: '/static/img/logo.png'
        });
        
        // Chiudi automaticamente dopo 5 secondi
        setTimeout(() => { notification.close(); }, 5000);
        
        // Aggiorna le notifiche quando viene cliccata
        notification.onclick = function() {
            loadNotifications();
            window.focus();
            notification.close();
        };
    }
    
    /**
     * Visualizza le notifiche nel dropdown
     * @param {Array} notifications - Lista di notifiche
     */
    function renderNotifications(notifications) {
        if (!notificationsList) return;
        
        if (notifications.length === 0) {
            notificationsList.innerHTML = `
                <div class="text-center p-3 text-muted">
                    <i class="fas fa-bell-slash"></i> Nessuna notifica
                </div>
            `;
            return;
        }
        
        let html = '';
        notifications.forEach(notification => {
            const levelClass = {
                'info': 'text-info',
                'success': 'text-success',
                'warning': 'text-warning',
                'error': 'text-danger'
            }[notification.level] || 'text-info';
            
            const icon = {
                'info': 'info-circle',
                'success': 'check-circle',
                'warning': 'exclamation-triangle',
                'error': 'exclamation-circle'
            }[notification.level] || 'info-circle';
            
            // Formatta la data
            const date = new Date(notification.created_at);
            const formattedDate = date.toLocaleString();
            
            html += `
                <div class="dropdown-item notification-item ${notification.read ? '' : 'bg-dark'}" data-id="${notification.id}">
                    <div class="d-flex align-items-center">
                        <div class="notification-icon ${levelClass} me-2">
                            <i class="fas fa-${icon}"></i>
                        </div>
                        <div class="notification-content flex-grow-1">
                            <div class="notification-title fw-bold">${notification.title}</div>
                            <div class="notification-message small">${notification.message}</div>
                            <div class="notification-time text-muted mt-1" style="font-size: 0.7rem;">
                                <i class="far fa-clock"></i> ${formattedDate}
                            </div>
                        </div>
                        ${notification.read ? '' : `
                            <button class="btn btn-sm text-muted mark-read-btn p-0 ms-2" 
                                    data-id="${notification.id}" 
                                    title="Segna come letta">
                                <i class="fas fa-check"></i>
                            </button>
                        `}
                    </div>
                </div>
            `;
        });
        
        notificationsList.innerHTML = html;
        
        // Aggiungi event listeners ai pulsanti
        document.querySelectorAll('.mark-read-btn').forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                markAsRead(this.getAttribute('data-id'));
            });
        });
        
        // Quando si clicca su una notifica non letta, segnarla come letta
        document.querySelectorAll('.notification-item:not(.read)').forEach(item => {
            item.addEventListener('click', function() {
                const id = this.getAttribute('data-id');
                markAsRead(id);
            });
        });
    }
    
    /**
     * Segna una notifica come letta
     * @param {string} id - ID della notifica
     */
    function markAsRead(id) {
        fetch(`/api/notifications/mark-read/${id}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                loadNotifications(); // Ricarica le notifiche
            }
        })
        .catch(error => {
            console.error('Errore nel segnare la notifica come letta:', error);
        });
    }
    
    /**
     * Segna tutte le notifiche come lette
     */
    function markAllAsRead() {
        fetch('/api/notifications/mark-all-read', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                loadNotifications(); // Ricarica le notifiche
            }
        })
        .catch(error => {
            console.error('Errore nel segnare tutte le notifiche come lette:', error);
        });
    }
    
    /**
     * Avvia il polling per le nuove notifiche
     */
    function startNotificationPolling() {
        // Controlla nuove notifiche ogni 60 secondi
        setInterval(() => {
            loadNotifications();
        }, 60000);
    }
    
    // Inizializzazione del sistema di notifiche
    
    // Aggiungi gestori eventi
    if (markAllReadBtn) {
        markAllReadBtn.addEventListener('click', function(e) {
            e.preventDefault();
            markAllAsRead();
        });
    }
    
    // Carica le notifiche all'apertura del dropdown
    const notificationsDropdown = document.getElementById('notificationsDropdown');
    if (notificationsDropdown) {
        notificationsDropdown.addEventListener('show.bs.dropdown', function() {
            loadNotifications();
        });
    }
    
    // Richiedi il permesso per le notifiche
    requestNotificationPermission();
    
    // Carica le notifiche all'avvio
    loadNotifications();
    
    // Avvia il polling per nuove notifiche
    startNotificationPolling();
}

/**
 * Inizializzazione dell'applicazione
 */
document.addEventListener('DOMContentLoaded', function() {
    // Attiva i tooltips di Bootstrap
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    });
    
    // Inizializza la pagina dei job attivi se siamo nella home
    if (document.getElementById('active-jobs-container')) {
        initializeActiveJobsPage();
    }
    
    // Gestione conferma eliminazione
    document.querySelectorAll('.confirm-action').forEach(element => {
        element.addEventListener('click', function(e) {
            if (!confirm(this.getAttribute('data-confirm-message') || 'Are you sure?')) {
                e.preventDefault();
                return false;
            }
        });
    });
    
    // Gestione validazione moduli
    document.querySelectorAll('form.needs-validation').forEach(form => {
        form.addEventListener('submit', function(e) {
            if (!form.checkValidity()) {
                e.preventDefault();
                e.stopPropagation();
            }
            form.classList.add('was-validated');
        });
    });
    
    // Sistema di notifiche del browser
    initNotificationSystem();
});

// Sistema di notifiche
function initNotificationSystem() {
    const notificationBadge = document.getElementById('notificationBadge');
    const notificationsList = document.getElementById('notifications-list');
    const markAllReadBtn = document.getElementById('markAllReadBtn');
    let notificationsEnabled = false;
    let unreadCount = 0;
    
    // Funzione per richiedere il permesso per le notifiche
    function requestNotificationPermission() {
        if (!("Notification" in window)) {
            console.log("Questo browser non supporta le notifiche desktop");
            return;
        }
        
        if (Notification.permission !== "granted" && Notification.permission !== "denied") {
            Notification.requestPermission();
        }
    }
    
    // Carica le notifiche
    function loadNotifications() {
        if (!notificationsList) return;
        
        fetch('/api/notifications?limit=10')
            .then(response => response.json())
            .then(data => {
                notificationsEnabled = data.settings.notifications_enabled;
                unreadCount = data.unread_count;
                updateNotificationBadge();
                renderNotifications(data.notifications);
            })
            .catch(error => {
                console.error('Errore nel caricamento delle notifiche:', error);
                notificationsList.innerHTML = `
                    <div class="text-center p-3 text-muted">
                        <i class="fas fa-exclamation-circle"></i> Errore nel caricamento delle notifiche
                    </div>
                `;
            });
    }
    
    // Aggiorna il badge con il conteggio delle notifiche non lette
    function updateNotificationBadge() {
        if (!notificationBadge) return;
        
        if (unreadCount > 0) {
            notificationBadge.textContent = unreadCount > 99 ? '99+' : unreadCount;
            notificationBadge.style.display = 'inline-block';
        } else {
            notificationBadge.style.display = 'none';
        }
    }
    
    // Invia una notifica al browser
    function sendBrowserNotification(title, message) {
        if (!notificationsEnabled) return;
        if (Notification.permission !== "granted") return;
        
        const notification = new Notification(title, {
            body: message,
            icon: '/static/img/logo.png'
        });
        
        // Chiudi automaticamente dopo 5 secondi
        setTimeout(() => { notification.close(); }, 5000);
        
        // Aggiorna le notifiche quando viene cliccata
        notification.onclick = function() {
            loadNotifications();
            window.focus();
            notification.close();
        };
    }
    
    // Render delle notifiche nel dropdown
    function renderNotifications(notifications) {
        if (!notificationsList) return;
        
        if (notifications.length === 0) {
            notificationsList.innerHTML = `
                <div class="text-center p-3 text-muted">
                    <i class="fas fa-bell-slash"></i> Nessuna notifica
                </div>
            `;
            return;
        }
        
        let html = '';
        notifications.forEach(notification => {
            const levelClass = {
                'info': 'text-info',
                'success': 'text-success',
                'warning': 'text-warning',
                'error': 'text-danger'
            }[notification.level] || 'text-info';
            
            const icon = {
                'info': 'info-circle',
                'success': 'check-circle',
                'warning': 'exclamation-triangle',
                'error': 'exclamation-circle'
            }[notification.level] || 'info-circle';
            
            // Formatta la data
            const date = new Date(notification.created_at);
            const formattedDate = date.toLocaleString();
            
            html += `
                <div class="dropdown-item notification-item ${notification.read ? '' : 'bg-dark'}" data-id="${notification.id}">
                    <div class="d-flex align-items-center">
                        <div class="notification-icon ${levelClass} me-2">
                            <i class="fas fa-${icon}"></i>
                        </div>
                        <div class="notification-content flex-grow-1">
                            <div class="notification-title fw-bold">${notification.title}</div>
                            <div class="notification-message small">${notification.message}</div>
                            <div class="notification-time text-muted mt-1" style="font-size: 0.7rem;">
                                <i class="far fa-clock"></i> ${formattedDate}
                            </div>
                        </div>
                        ${notification.read ? '' : `
                            <button class="btn btn-sm text-muted mark-read-btn p-0 ms-2" 
                                    data-id="${notification.id}" 
                                    title="Segna come letta">
                                <i class="fas fa-check"></i>
                            </button>
                        `}
                    </div>
                </div>
            `;
        });
        
        notificationsList.innerHTML = html;
        
        // Aggiungi event listeners per i pulsanti "Segna come letta"
        document.querySelectorAll('.mark-read-btn').forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                markAsRead(this.getAttribute('data-id'));
            });
        });
        
        // Quando si clicca su una notifica non letta, segnarla come letta
        document.querySelectorAll('.notification-item:not(.read)').forEach(item => {
            item.addEventListener('click', function() {
                const id = this.getAttribute('data-id');
                markAsRead(id);
            });
        });
    }
    
    // Segna una notifica come letta
    function markAsRead(id) {
        fetch(`/api/notifications/mark-read/${id}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                loadNotifications(); // Ricarica le notifiche
            }
        })
        .catch(error => {
            console.error('Errore nel segnare la notifica come letta:', error);
        });
    }
    
    // Segna tutte le notifiche come lette
    function markAllAsRead() {
        fetch('/api/notifications/mark-all-read', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                loadNotifications(); // Ricarica le notifiche
            }
        })
        .catch(error => {
            console.error('Errore nel segnare tutte le notifiche come lette:', error);
        });
    }
    
    // Polling per nuove notifiche
    function startNotificationPolling() {
        // Controlla nuove notifiche ogni 60 secondi
        setInterval(() => {
            loadNotifications();
        }, 60000);
    }
    
    // Setup degli event listeners
    if (markAllReadBtn) {
        markAllReadBtn.addEventListener('click', function(e) {
            e.preventDefault();
            markAllAsRead();
        });
    }
    
    // Carica le notifiche all'apertura del dropdown
    const notificationsDropdown = document.getElementById('notificationsDropdown');
    if (notificationsDropdown) {
        notificationsDropdown.addEventListener('show.bs.dropdown', function() {
            loadNotifications();
        });
    }
    
    // Richiedi il permesso per le notifiche
    requestNotificationPermission();
    
    // Carica le notifiche all'avvio
    loadNotifications();
    
    // Avvia il polling per nuove notifiche
    startNotificationPolling();
};
