# WhatsApp Core Community — Odoo 19

> **Phase 1: Core WhatsApp Integration**
> A production-ready WhatsApp Cloud API integration for Odoo 19 Community Edition.
> Mimics the configuration experience of Odoo Enterprise's WhatsApp module.

---

## 📦 Module Information

| Field | Value |
|-------|-------|
| **Module Name** | `whatsapp_core_community` |
| **Version** | `19.0.1.0.0` |
| **Dependencies** | `base`, `mail`, `contacts` |
| **License** | LGPL-3 |
| **API** | Meta WhatsApp Cloud API (Official) |

---

## 🏗 Architecture Overview

```
whatsapp_core_community/
├── __manifest__.py
├── __init__.py
├── models/
│   ├── __init__.py
│   ├── res_config_settings.py     # Settings + Test/Validate actions
│   ├── whatsapp_service.py        # ⭐ Core API Service Layer
│   ├── whatsapp_message_log.py    # Message Logging Model
│   └── res_partner.py             # Partner Extensions
├── wizard/
│   ├── __init__.py
│   ├── whatsapp_send_wizard.py    # Manual Send Wizard
│   └── whatsapp_send_wizard_views.xml
├── controllers/
│   ├── __init__.py
│   └── whatsapp_webhook.py        # Inbound Webhook Handler
├── views/
│   ├── res_config_settings_views.xml   # Settings UI
│   ├── whatsapp_message_log_views.xml  # Log List/Form
│   ├── res_partner_views.xml          # Partner Smart Buttons
│   └── whatsapp_menu.xml              # Menu Structure
├── security/
│   ├── ir.model.access.csv
│   └── whatsapp_security.xml
├── data/
│   └── whatsapp_data.xml
└── static/
    └── description/
        └── icon.png
```

---

## ✅ Prerequisites

### 1. Meta Developer Account Setup

1. Go to [developers.facebook.com](https://developers.facebook.com)
2. Create an App → **Business** type
3. Add **WhatsApp** product to your app
4. Go to **WhatsApp → API Setup**

### 2. Collect Your Credentials

| Credential | Where to Find |
|-----------|---------------|
| **Business Account ID** | Meta Business Manager → Settings → Business Account ID |
| **Phone Number ID** | WhatsApp → API Setup → Phone Number ID |
| **Permanent Access Token** | System Users → Generate Token (select WhatsApp permissions) |
| **Webhook Verify Token** | A secret string **you choose yourself** |

> **Tip:** For production, generate a System User token with `whatsapp_business_messaging` and `whatsapp_business_management` permissions. Do NOT use temporary tokens.

---

## 🚀 Installation

### Step 1: Place Module
```
<your_odoo_root>/custom/whatsapp_core_community/
```

### Step 2: Verify `addons_path` in `odoo.conf`
```ini
addons_path = addons, custom
```

### Step 3: Install Module
```bash
# Restart Odoo
python odoo-bin -c odoo.conf -u whatsapp_core_community --stop-after-init
```

Or via Odoo UI:
- Settings → Activate Developer Mode
- Apps → Search "WhatsApp Core Community" → Install

---

## ⚙️ Configuration

### Step 1: Open WhatsApp Settings
**Settings → General Settings → WhatsApp**

### Step 2: Enable WhatsApp
Toggle **Enable WhatsApp Integration** to ON.

### Step 3: Fill in Credentials

| Field | Description |
|-------|-------------|
| Business Account ID | From Meta Business Manager |
| Phone Number ID | From Meta Developer Portal |
| Permanent Access Token | Long-lived system user token |
| Webhook Verify Token | Your custom secret string |
| API Version | Default: `v19.0` |

### Step 4: Save & Test
1. Click **Save** (top of page)
2. Click **🔌 Test Connection** → Should show green success popup
3. Click **✔ Validate Credentials** → Should confirm account name

---

## 🔄 Webhook Configuration (Meta Portal)

### Your Webhook URL
```
https://your-odoo-domain.com/whatsapp/webhook
```

> **For local development:** Use [ngrok](https://ngrok.com) to expose your local Odoo:
> ```bash
> ngrok http 8072
> ```
> Then use the `https://xxxxx.ngrok.io/whatsapp/webhook` URL.

### Steps in Meta Developer Portal:
1. WhatsApp → Configuration → Webhooks
2. **Callback URL:** `https://your-domain.com/whatsapp/webhook`
3. **Verify Token:** Same value as in Odoo Settings
4. Click **Verify and Save**
5. Subscribe to **messages** webhook field

---

## 💬 Sending Messages

### From a Contact (Partner)

1. Open any Contact (`Contacts` app or search)
2. Set their **WhatsApp Number** (E.164 format: `+919876543210`)
3. Optionally toggle **WhatsApp Opt-In**
4. Click **📱 Send WhatsApp** button (top right)

### Message Types

#### ✉️ Text Message
- Select **Text Message**
- Type your message (max 4096 chars)
- Click **📱 Send WhatsApp**

#### 📋 Template Message
- Select **Template Message**
- Enter the **Template Name** (exact name from Meta Business Manager)
- Set **Language Code** (e.g., `en_US`, `hi`, `ta`)
- Fill variable fields if your template uses `{{1}}`, `{{2}}`, etc.
- Click **📱 Send WhatsApp**

> **Note:** Template messages must be approved by Meta before use.

#### 📎 Media / Document
- Select **Media / Document**
- Choose or upload an **attachment** (image, PDF, video, audio)
- Optional **caption**
- Click **📱 Send WhatsApp**

---

## 📜 Message Logs

Access via: **WhatsApp → Message Logs**

Shows:
- All sent/received messages
- Status (Sent ✔ / Failed ✖ / Received ↙)
- Message preview
- Full JSON payload (for debugging)
- API response

---

## 🔄 Inbound Messages (Webhook)

When a contact sends you a WhatsApp message:

1. Meta pushes the message to `/whatsapp/webhook`
2. Module looks up the sender's phone number in partners
3. If found → logs message + posts in chatter
4. If not found → creates a new contact automatically
5. Idempotent: duplicate webhook deliveries are ignored

---

## 🛡 Security

| Access Level | Can Do |
|-------------|--------|
| System Administrator | Full access: configure, send, view all logs |
| Internal User | Send messages, view message logs (read-only) |
| Public / Portal | No access |

---

## 🧩 Using the Service Layer (For Developers)

All future automations **must use** `whatsapp.service` directly:

```python
# Send a text message
service = self.env['whatsapp.service']
result = service.send_text_message(partner, "Hello from Odoo!")

# Send a template
result = service.send_template_message(
    partner=partner,
    template_name='order_confirmation',
    language_code='en_US',
    variables=['John', 'ORD-001', '₹5,000'],
)

# Send a PDF
result = service.send_media_message(
    partner=partner,
    attachment_id=attachment.id,
    caption='Your Invoice',
)

# Check result
if result['success']:
    print(f"Sent! Message ID: {result['message_id']}")
else:
    print(f"Failed: {result['error']}")
```

---

## 🧪 Testing Checklist

- [ ] Token validation works (Settings → Test Connection)
- [ ] Credentials validation works (Settings → Validate Credentials)
- [ ] Text message sends successfully
- [ ] Template message sends successfully
- [ ] Media (PDF/image) sends successfully
- [ ] Webhook GET verification works (Meta handshake)
- [ ] Webhook POST receives inbound messages
- [ ] Message logs created for all sends
- [ ] Chatter updated on partner after send
- [ ] New contact created when unknown sender messages in
- [ ] Failed sends logged with error detail
- [ ] No automatic triggers executed

---

## 🚧 What's NOT in Phase 1

- ❌ CRM automation
- ❌ Stage triggers
- ❌ Workflow automation
- ❌ Scheduled message sending
- ❌ WhatsApp template management UI (use Meta Business Manager)

These will be added in Phase 2 using the `whatsapp.service` engine.

---

## 📞 Support

For issues: check `odoo.log` for `[whatsapp]` prefixed log entries.

Enable debug logging temporarily:
```ini
log_handler = :DEBUG
```

Then filter:
```bash
grep -i whatsapp odoo.log | tail -50
```
