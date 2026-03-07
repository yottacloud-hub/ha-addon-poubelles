# 🗑️ Add-on Home Assistant — Gestion Poubelles

Gère les rappels de sortie des poubelles jaune et verte avec scan OCR du calendrier annuel, notifications et confirmations.

## Fonctionnalités

- **📷 Scan OCR** : Uploadez une photo ou PDF de votre calendrier de collecte annuel. L'OCR (Tesseract) extrait automatiquement les dates et types de poubelles.
- **📅 Calendrier** : Vue mensuelle colorée des collectes. Ajout manuel de dates unitaires ou récurrentes.
- **🔔 Rappels** : Notification la veille de chaque collecte à l'heure de votre choix via le service de notification HA de votre choix.
- **✅ Confirmation** : Boutons pour confirmer que la poubelle est sortie ou marquer comme manquée. Statistiques de suivi.
- **⚙️ Réglages** : Heure de rappel personnalisable, activation/désactivation, service de notification configurable.

## Installation

### Méthode 1 : Dépôt local

1. Copiez le dossier `ha-addon-poubelles` dans le répertoire `/addons/` de votre installation Home Assistant :
   ```
   /addons/ha-addon-poubelles/
   ├── config.yaml
   ├── Dockerfile
   ├── icon.svg
   ├── README.md
   └── rootfs/
       ├── etc/services.d/poubelles/run
       └── opt/poubelles/
           ├── app.py
           ├── templates/index.html
           └── static/
   ```

2. Dans Home Assistant, allez dans **Paramètres → Modules complémentaires → Boutique des modules complémentaires**

3. Cliquez sur **⋮** (menu 3 points) en haut à droite → **Vérifier les mises à jour**

4. L'add-on "Gestion Poubelles" apparaît dans la section **Dépôts locaux**

5. Cliquez dessus puis **Installer**

### Méthode 2 : Dépôt GitHub

1. Poussez ce dossier dans un dépôt GitHub
2. Dans HA : **Paramètres → Modules complémentaires → Boutique → ⋮ → Dépôts → Ajouter** l'URL du dépôt
3. Installez l'add-on

## Configuration

| Option | Défaut | Description |
|--------|--------|-------------|
| `reminder_hour` | `19` | Heure du rappel (0-23) |
| `reminder_minute` | `0` | Minute du rappel (0-59) |
| `notification_service` | `notify.notify` | Service HA de notification |

## Utilisation

### 1. Scanner votre calendrier

- Allez dans l'onglet **📷 Scanner**
- Uploadez la photo/PDF de votre calendrier annuel de collecte
- L'OCR extrait les dates automatiquement
- Vérifiez le résultat et corrigez dans l'onglet **📅 Calendrier** si nécessaire

### 2. Ajout manuel (optionnel)

Si l'OCR n'est pas parfait, vous pouvez :
- Ajouter des dates une par une
- Utiliser l'ajout récurrent (ex: chaque mardi, toutes les 2 semaines)

### 3. Recevoir les rappels

- La veille de chaque collecte, une notification est envoyée à l'heure configurée
- La notification contient des **boutons d'action** :
  - ✅ **C'est fait !** — confirme que la poubelle est sortie
  - ⏰ **Rappeler dans 1h** — relance après 1 heure

### 4. Confirmer dans l'interface

- Le tableau de bord affiche les prochaines collectes
- Boutons ✓ (sortie) et ✗ (manquée) pour chaque poubelle
- Les statistiques s'actualisent automatiquement

## Notifications actionnables

Pour que les boutons d'action fonctionnent sur les notifications, vous devez configurer les automations HA correspondantes.

Exemple d'automation `automations.yaml` :

```yaml
- alias: "Poubelles - Confirmation sortie"
  trigger:
    - platform: event
      event_type: mobile_app_notification_action
      event_data:
        action: "BINS_DONE"
  action:
    - service: rest_command.poubelles_confirm
      data:
        date: "{{ now().date() + timedelta(days=1) }}"
        status: "done"

- alias: "Poubelles - Rappel snooze"
  trigger:
    - platform: event
      event_type: mobile_app_notification_action
      event_data:
        action: "BINS_SNOOZE"
  action:
    - delay: "01:00:00"
    - service: notify.notify
      data:
        title: "🗑️ Rappel Poubelles"
        message: "N'oubliez pas de sortir vos poubelles !"
```

## Dépannées

- **L'OCR ne détecte rien** : Essayez avec une image plus nette, bien éclairée, bien cadrée
- **Pas de notification** : Vérifiez le service de notification dans les réglages et testez avec le bouton de test
- **Dates incorrectes** : Corrigez manuellement dans l'onglet Calendrier

## Technique

- **Backend** : Python 3 / Flask
- **OCR** : Tesseract (français)
- **Scheduler** : APScheduler (cron)
- **Stockage** : JSON dans `/share/poubelles/`
- **Intégration HA** : API Supervisor (notifications, ingress)
