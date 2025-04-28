**Provider più comuni**

1. Google Drive

    Dove registrarsi:
   
      Google Cloud Console
    Procedura:
   
      Crea un progetto.
      Abilita Google Drive API.
      Vai in APIs & Services > Credentials.
      Crea OAuth 2.0 Client ID → Tipo: Desktop App.
    Ti darà:
   
      client_id
      client_secret
    Token generation:
      Quando configuri rclone (rclone config), lui ti guiderà per aprire un URL di autorizzazione → autorizzi → copia il codice → si genera il token automaticamente.

3. Dropbox

    Dove registrarsi: Dropbox App Console
   
    Procedura:
      Crea una nuova app:
      API: Scoped Access
      Type: Full Dropbox o App Folder
   
    Ti darà:
      client_id (App key)
      client_secret (App secret)
   
    Token generation:
      Idem: rclone config ti farà aprire il link di autorizzazione → autorizzi → genera token.

5. OneDrive (Microsoft)

    Dove registrarsi: Microsoft Azure Portal
   
    Procedura:
       Azure Active Directory → App registrations → New registration
       Nome: quello che vuoi
       Redirect URI: http://localhost:53682/
   
    Crea app → prendi:
      client_id
      Importante: Genera client secret manualmente in "Certificates & Secrets" → "New client secret"
   
    Token generation:
      Sempre via rclone config — autorizzi la tua app.

7. Mega.nz

    Non serve client_id e client_secret.
    Usa username/password e genera token da solo.

8. S3 (Amazon AWS / MinIO ecc.)

    Dove registrarsi: AWS Management Console
   
    Procedura:
      IAM → Users → Create new user
      Permissions: Access to S3
   
    Ti dà:
      AWS_ACCESS_KEY_ID → simile a client_id
      AWS_SECRET_ACCESS_KEY → simile a client_secret
   
   Token generation:
      Non serve token separato: firmi le richieste direttamente.
