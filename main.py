import os, json, threading, uuid
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = [980702308, 1360061189]
PRODUCTS_FILE = "products.json"

carts, orders, user_steps, waiting_admin = {}, {}, {}, {}

web = Flask(__name__)

@web.route("/")
def home():
    return "Do Brazil Bot is running!"

def load_products():
    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["products"]

def save_products(products):
    with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
        json.dump({"products": products}, f, ensure_ascii=False, indent=2)

def total_cart(cart, products):
    return sum(products[int(i)]["price"] * q for i, q in cart.items())

def cart_text(cart, products):
    text = ""
    for i, q in cart.items():
        p = products[int(i)]
        text += f"🍦 {p['name']} x{q} = {p['price'] * q}€\n"
    text += f"\n💰 Total : {total_cart(cart, products)}€"
    return text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🇧🇷 Bienvenue chez Do Brazil !\n\n"
        "🍦 /produits - Voir les produits\n"
        "🛒 /panier - Voir ton panier"
    )

async def produits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = load_products()
    text = "🍦 Produits disponibles :\n\n"
    keyboard = []

    for i, p in enumerate(products):
        if p["stock"] > 0:
            text += f"{i+1}. {p['name']} — {p['price']}€ — Stock : {p['stock']}\n"
            keyboard.append([InlineKeyboardButton(f"➕ {p['name']}", callback_data=f"add_{i}")])
        else:
            text += f"{i+1}. {p['name']} — ❌ Rupture\n"

    keyboard.append([InlineKeyboardButton("🛒 Voir panier", callback_data="cart")])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_cart(chat_id, context):
    cart = carts.get(chat_id, {})
    products = load_products()

    if not cart:
        await context.bot.send_message(chat_id, "🛒 Ton panier est vide.")
        return

    keyboard = []
    for i in cart:
        p = products[int(i)]
        keyboard.append([
            InlineKeyboardButton(f"➖ {p['name']}", callback_data=f"remove_{i}"),
            InlineKeyboardButton(f"➕ {p['name']}", callback_data=f"add_{i}")
        ])

    keyboard.append([InlineKeyboardButton("✅ Valider la commande", callback_data="checkout")])
    await context.bot.send_message(
        chat_id,
        "🛒 Ton panier :\n\n" + cart_text(cart, products),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def panier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_cart(update.message.chat_id, context)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data
    products = load_products()

    if data.startswith("add_"):
        idx = data.split("_")[1]
        p = products[int(idx)]
        current = carts.get(chat_id, {}).get(idx, 0)

        if current + 1 > p["stock"]:
            await query.message.reply_text("❌ Stock insuffisant.")
            return

        carts.setdefault(chat_id, {})[idx] = current + 1
        await query.message.reply_text(f"✅ Ajouté : {p['name']}")

    elif data.startswith("remove_"):
        idx = data.split("_")[1]
        if chat_id in carts and idx in carts[chat_id]:
            carts[chat_id][idx] -= 1
            if carts[chat_id][idx] <= 0:
                del carts[chat_id][idx]
        await show_cart(chat_id, context)

    elif data == "cart":
        await show_cart(chat_id, context)

    elif data == "checkout":
        if not carts.get(chat_id):
            await query.message.reply_text("🛒 Ton panier est vide.")
            return
        user_steps[chat_id] = {"step": "nom"}
        await query.message.reply_text("👤 Quel est votre nom ?")

    elif data.startswith("accept_"):
        if query.from_user.id not in ADMIN_IDS:
            return
        order_id = data.split("_")[1]
        waiting_admin[query.from_user.id] = {"order_id": order_id, "step": "jour_final"}
        await query.message.reply_text("📅 Jour définitif de retrait ?")

    elif data.startswith("reject_"):
        if query.from_user.id not in ADMIN_IDS:
            return
        order_id = data.split("_")[1]
        order = orders.get(order_id)
        if order:
            await context.bot.send_message(order["client_id"], "❌ Votre commande a été refusée.\n\n🇧🇷 Do Brazil vous remercie.")
            await query.message.reply_text("Commande refusée.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    text = update.message.text

    if user_id in waiting_admin:
        data = waiting_admin[user_id]
        order = orders[data["order_id"]]

        if data["step"] == "jour_final":
            data["jour_final"] = text
            data["step"] = "heure_finale"
            await update.message.reply_text("🕒 Heure définitive de retrait ?")
            return

        if data["step"] == "heure_finale":
            data["heure_finale"] = text
            data["step"] = "adresse"
            await update.message.reply_text("📍 Adresse de retrait ?")
            return

        if data["step"] == "adresse":
            products = load_products()

            for idx, qty in order["cart"].items():
                if products[int(idx)]["stock"] < qty:
                    await update.message.reply_text("❌ Stock insuffisant.")
                    waiting_admin.pop(user_id)
                    return

            for idx, qty in order["cart"].items():
                products[int(idx)]["stock"] -= qty

            save_products(products)

            await context.bot.send_message(
                order["client_id"],
                "✅ Votre commande a été acceptée !\n\n"
                f"📅 Jour de retrait : {data['jour_final']}\n"
                f"🕒 Heure de retrait : {data['heure_finale']}\n"
                f"📍 Adresse : {text}\n\n"
                "💵 Paiement uniquement en liquide.\n\n"
                "🇧🇷 Do Brazil vous remercie."
            )

            await update.message.reply_text("✅ Commande validée et stock déduit.")
            waiting_admin.pop(user_id)
            return

    if chat_id in user_steps:
        step_data = user_steps[chat_id]
        step = step_data["step"]

        if step == "nom":
            step_data["nom"] = text
            step_data["step"] = "prenom"
            await update.message.reply_text("👤 Quel est votre prénom ?")
            return

        if step == "prenom":
            step_data["prenom"] = text
            step_data["step"] = "telephone"
            await update.message.reply_text("📞 Votre numéro de téléphone ?")
            return

        if step == "telephone":
            step_data["telephone"] = text
            step_data["step"] = "jour"
            await update.message.reply_text("📅 Jour souhaité de retrait ?")
            return

        if step == "jour":
            step_data["jour"] = text
            step_data["step"] = "heure"
            await update.message.reply_text("🕒 Heure souhaitée de retrait ?")
            return

        if step == "heure":
            step_data["heure"] = text
            products = load_products()
            cart = carts.get(chat_id, {})
            order_id = str(uuid.uuid4())[:8]

            orders[order_id] = {
                "client_id": chat_id,
                "cart": cart.copy(),
                **step_data
            }

            recap = cart_text(cart, products)

            await update.message.reply_text(
                "🇧🇷 Do Brazil vous remercie pour votre commande !\n\n"
                "📋 Récapitulatif :\n\n"
                f"👤 Nom : {step_data['nom']}\n"
                f"👤 Prénom : {step_data['prenom']}\n"
                f"📞 Téléphone : {step_data['telephone']}\n"
                f"📅 Jour souhaité : {step_data['jour']}\n"
                f"🕒 Heure souhaitée : {step_data['heure']}\n\n"
                f"{recap}\n\n"
                "💵 Paiement uniquement en liquide.\n"
                "⏳ Votre commande est en attente de validation."
            )

            admin_text = (
                f"🔔 Nouvelle commande #{order_id}\n\n"
                f"👤 {step_data['prenom']} {step_data['nom']}\n"
                f"📞 {step_data['telephone']}\n"
                f"📅 Jour souhaité : {step_data['jour']}\n"
                f"🕒 Heure souhaitée : {step_data['heure']}\n\n"
                f"{recap}"
            )

            keyboard = [[
                InlineKeyboardButton("✅ Accepter", callback_data=f"accept_{order_id}"),
                InlineKeyboardButton("❌ Refuser", callback_data=f"reject_{order_id}")
            ]]

            for admin in ADMIN_IDS:
                await context.bot.send_message(admin, admin_text, reply_markup=InlineKeyboardMarkup(keyboard))

            carts[chat_id] = {}
            user_steps.pop(chat_id)
            return

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("produits", produits))
    app.add_handler(CommandHandler("panier", panier))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()
