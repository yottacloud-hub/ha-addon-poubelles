# Add-on Home Assistant — Gestion Poubelles

Gere les rappels de sortie des poubelles jaune et verte avec scan du calendrier annuel, notifications sur mobile et confirmations.

## Fonctionnalites

- **Scan intelligent** : Uploadez une photo ou PDF de votre calendrier de collecte. La detection par couleur extrait automatiquement les dates (compatible Toulouse Metropole et calendriers en grille similaires).
- **Calendrier** : Vue mensuelle coloree des collectes. Ajout manuel de dates unitaires ou recurrentes. Suppression individuelle ou totale.
- **Rappels mobile** : Notification la veille de chaque collecte sur vos telephones via l'app HA Companion. Multi-appareils supportes.
- **Confirmation** : Boutons pour confirmer que la poubelle est sortie ou marquer comme manquee. Statistiques de suivi.
- **Reglages** : Heure de rappel personnalisable, selection des appareils de notification, activation/desactivation.

## Installation

### Depot Add-on Home Assistant (recommande)

1. Dans Home Assistant : **Parametres > Modules complementaires > Boutique des modules complementaires**
2. Cliquez sur le menu 3 points en haut a droite > **Depots**
3. Ajoutez l'URL : `https://github.com/yottacloud-hub/ha-addon-poubelles`
4. Cliquez **Ajouter** puis fermez
5. Recherchez "Gestion Poubelles" dans la boutique et cliquez **Installer**

### Methode locale

1. Copiez le dossier `gestion_poubelles/` dans le repertoire `/addons/` de votre installation Home Assistant
2. Dans HA : **Parametres > Modules complementaires > Boutique > menu > Verifier les mises a jour**
3. L'add-on apparait dans la section **Depots locaux**

## Configuration

| Option | Defaut | Description |
|--------|--------|-------------|
| `reminder_hour` | `19` | Heure du rappel (0-23) |
| `reminder_minute` | `0` | Minute du rappel (0-59) |
| `notification_service` | `notify.notify` | Service par defaut (remplace par la selection d'appareils) |

## Utilisation

### 1. Scanner votre calendrier

- Allez dans l'onglet **Scanner**
- Uploadez la photo/PDF de votre calendrier annuel de collecte
- La detection par couleur identifie les cellules grises (ordures menageres) et jaunes (recyclables)
- Verifiez le resultat et supprimez les erreurs dans l'onglet **Calendrier**

### 2. Ajout manuel (optionnel)

Si la detection n'est pas parfaite, vous pouvez :
- Ajouter des dates une par une
- Utiliser l'ajout recurrent (ex: chaque mardi, toutes les 2 semaines)
- Supprimer des dates individuellement (clic sur un jour colore dans le calendrier ou bouton poubelle dans le tableau de bord)

### 3. Configurer les notifications

- Allez dans l'onglet **Reglages**
- Dans la section **Appareils de notification**, vos telephones avec l'app HA Companion apparaissent automatiquement
- Cochez les appareils qui doivent recevoir les rappels
- Cliquez **Enregistrer la selection**
- Testez avec le bouton **Envoyer un test**

**Important** : Vous devez avoir l'application [Home Assistant Companion](https://companion.home-assistant.io/) installee sur votre telephone. Le service de notification correspondant (`notify.mobile_app_<nom_appareil>`) est cree automatiquement par HA.

### 4. Recevoir les rappels

- La veille de chaque collecte, une notification est envoyee a l'heure configuree
- Confirmez dans l'interface web de l'add-on via les boutons dans le tableau de bord

## Depannage

- **Le scan ne detecte rien** : Verifiez que l'image est nette. Le systeme detecte les couleurs des cellules (gris/jaune), pas le texte. Les calendriers en grille type Toulouse Metropole fonctionnent le mieux.
- **Pas de notification** : Allez dans Reglages > Appareils, verifiez que vos appareils sont detectes et coches. Utilisez le bouton de test. Consultez les logs de l'add-on pour les erreurs.
- **Dimanches detectes a tort** : Utilisez le bouton poubelle pour supprimer les dates en trop, ou faites un reset complet et re-scannez.
- **Dates incorrectes** : Supprimez-les individuellement depuis le calendrier ou le tableau de bord.

## Technique

- **Backend** : Python 3 / Flask
- **Detection** : Analyse colorimetrique des cellules + Tesseract OCR (francais) pour la structure
- **Scheduler** : APScheduler (cron)
- **Stockage** : JSON dans `/share/poubelles/`
- **Integration HA** : API Supervisor (notifications, ingress, decouverte des services)
