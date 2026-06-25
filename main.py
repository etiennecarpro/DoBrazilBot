import os, json, threading, uuid, asyncio
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatMemberHandler, filters, ContextTypes
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
BOT_USERNAME = "DoBrazilShopBot"
PRODUCTS_FILE = "products.json"
ADMINS_FILE = "admins.json"
SUPER_ADMINS = [980702308, 1360061189]

carts = {}
orders = {}
user_steps = {}
waiting_admin = {}
admin_steps = {}

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

def load_admins():
    if not os.path.exists(ADMINS_FILE):
        save_admins(SUPER_ADMINS)
    with open(ADMINS_FILE, "r", encoding="utf-8") as f:
        admins = json.load(f)["admins"]
    return list(set(admins + SUPER_ADMINS))

def save_admins(admins):
    with open(ADMINS_FILE, "w", encoding="utf-8") as f:
        json.dump({"admins": list(set(admins + SUPER_ADMINS))}, f, indent=2)

def is_admin(user_id):
    return user_id in load_admins()

def total_cart(cart, products):
    return sum(products[int(i)]["price"] * q for i, q in cart.items())

def cart_text(cart, products):
    text = ""
    for i, q in cart.items():
        p = products[int(i)]
        text += f"🍦 {p['name']} x{q} = {p['price'] * q}€\n"
    text += f"\n💰 Total : {total_cart(cart, products)}€"
    return text

def private_order_button():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🛒 Commander mes XUP XUP", url=f"https://t.me/{BOT_USERNAME}?start=commande")
    ]])

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        await update.message.reply_text(
            "🇧🇷 Bonjour et bienvenue chez Do Brazil !\n\n"
            "🍦 Pour commander vos XUP XUP, il vous suffit d’appuyer sur le bouton ci-dessous.\n\n"
            "🔒 Toute votre commande se passera en message privé afin de protéger vos informations confidentielles.\n\n"
            "Vous recevrez ensuite un message de confirmation lorsque votre commande aura été validée.\n\n"
            "Merci et bonne dégustation 🇧🇷",
            reply_markup=private_order_button()
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text(
            "🔒 Pour commander en toute confidentialité, cliquez sur le bouton ci-dessous.",
            reply_markup=private_order_button()
        )
        return

    await update.message.reply_text(
        "🇧🇷 Bienvenue chez Do Brazil !\n\n"
        "🍦 /produits - Voir les produits\n"
        "🛒 /panier - Voir ton panier"
    )

async def produits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text(
            "🔒 Les commandes se passent en privé.",
            reply_markup=private_order_button()
        )
        return

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

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        return

    keyboard = [
        [InlineKeyboardButton("📦 Gérer les stocks", callback_data="admin_stock")],
        [InlineKeyboardButton("➕ Ajouter un produit", callback_data="admin_add_product")],
        [InlineKeyboardButton("🗑 Supprimer un produit", callback_data="admin_delete_product")],
        [InlineKeyboardButton("📋 Voir les commandes", callback_data="admin_orders")],
        [InlineKeyboardButton("👥 Gérer les admins", callback_data="admin_admins")]
    ]

    await update.message.reply_text("👑 Menu administrateur", reply_markup=InlineKeyboardMarkup(keyboard))

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user_id = query.from_user.id
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
        if not is_admin(user_id):
            return
        order_id = data.split("_")[1]
        waiting_admin[user_id] = {"order_id": order_id, "step": "jour_final"}
        await query.message.reply_text("📅 Jour définitif de retrait ?")

    elif data.startswith("reject_"):
        if not is_admin(user_id):
            return
        order_id = data.split("_")[1]
        order = orders.get(order_id)
        if order:
            await context.bot.send_message(order["client_id"], "❌ Votre commande a été refusée.\n\n🇧🇷 Do Brazil vous remercie.")
            await query.message.reply_text("Commande refusée.")

    elif data == "admin_stock" and is_admin(user_id):
        keyboard = []
        text = "📦 Gestion des stocks :\n\n"
        for i, p in enumerate(products):
            text += f"{i+1}. {p['name']} — Stock : {p['stock']} — Prix : {p['price']}€\n"
            keyboard.append([InlineKeyboardButton(f"🍦 {p['name']}", callback_data=f"stock_product_{i}")])
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("stock_product_") and is_admin(user_id):
        idx = int(data.split("_")[-1])
        p = products[idx]
        keyboard = [
            [
                InlineKeyboardButton("➕ +1", callback_data=f"stock_add_{idx}_1"),
                InlineKeyboardButton("➕ +5", callback_data=f"stock_add_{idx}_5"),
                InlineKeyboardButton("➕ +10", callback_data=f"stock_add_{idx}_10")
            ],
            [
                InlineKeyboardButton("➖ -1", callback_data=f"stock_sub_{idx}_1"),
                InlineKeyboardButton("➖ -5", callback_data=f"stock_sub_{idx}_5")
            ],
            [
                InlineKeyboardButton("✏️ Définir stock", callback_data=f"stock_set_{idx}"),
                InlineKeyboardButton("💰 Modifier prix", callback_data=f"price_set_{idx}")
            ]
        ]
        await query.message.reply_text(
            f"🍦 {p['name']}\nStock actuel : {p['stock']}\nPrix : {p['price']}€",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("stock_add_") and is_admin(user_id):
        _, _, idx, amount = data.split("_")
        products[int(idx)]["stock"] += int(amount)
        save_products(products)
        await query.message.reply_text("✅ Stock ajouté.")

    elif data.startswith("stock_sub_") and is_admin(user_id):
        _, _, idx, amount = data.split("_")
        products[int(idx)]["stock"] = max(0, products[int(idx)]["stock"] - int(amount))
        save_products(products)
        await query.message.reply_text("✅ Stock retiré.")

    elif data.startswith("stock_set_") and is_admin(user_id):
        idx = int(data.split("_")[-1])
        admin_steps[user_id] = {"step": "set_stock", "idx": idx}
        await query.message.reply_text("✏️ Nouveau stock ?")

    elif data.startswith("price_set_") and is_admin(user_id):
        idx = int(data.split("_")[-1])
        admin_steps[user_id] = {"step": "set_price", "idx": idx}
        await query.message.reply_text("💰 Nouveau prix ? Exemple : 2.50")

    elif data == "admin_add_product" and is_admin(user_id):
        admin_steps[user_id] = {"step": "add_name"}
        await query.message.reply_text("➕ Nom du produit ?")

    elif data == "admin_delete_product" and is_admin(user_id):
        keyboard = [[InlineKeyboardButton(f"🗑 {p['name']}", callback_data=f"delete_product_{i}")] for i, p in enumerate(products)]
        await query.message.reply_text("Choisis le produit à supprimer :", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("delete_product_") and is_admin(user_id):
        idx = int(data.split("_")[-1])
        removed = products.pop(idx)
        save_products(products)
        await query.message.reply_text(f"🗑 Produit supprimé : {removed['name']}")

    elif data == "admin_orders" and is_admin(user_id):
        if not orders:
            await query.message.reply_text("📋 Aucune commande pour le moment.")
            return
        text = "📋 Commandes :\n\n"
        for oid, o in orders.items():
            text += f"#{oid} — {o.get('prenom','')} {o.get('nom','')} — {o.get('jour','')} {o.get('heure','')}\n"
        await query.message.reply_text(text)

    elif data == "admin_admins" and is_admin(user_id):
        admins = load_admins()
        text = "👥 Administrateurs :\n\n" + "\n".join([str(a) for a in admins])
        keyboard = [
            [InlineKeyboardButton("➕ Ajouter admin", callback_data="admin_add_admin")],
            [InlineKeyboardButton("➖ Retirer admin", callback_data="admin_remove_admin")]
        ]
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_add_admin" and is_admin(user_id):
        admin_steps[user_id] = {"step": "add_admin"}
        await query.message.reply_text("Envoie l’ID Telegram du nouvel admin.")

    elif data == "admin_remove_admin" and is_admin(user_id):
        admin_steps[user_id] = {"step": "remove_admin"}
        await query.message.reply_text("Envoie l’ID Telegram de l’admin à retirer.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    text = update.message.text.strip()

    if user_id in admin_steps and is_admin(user_id):
        step = admin_steps[user_id]
        products = load_products()

        if step["step"] == "set_stock":
            products[step["idx"]]["stock"] = int(text)
            save_products(products)
            admin_steps.pop(user_id)
            await update.message.reply_text("✅ Stock mis à jour.")
            return

        if step["step"] == "set_price":
            products[step["idx"]]["price"] = float(text.replace(",", "."))
            save_products(products)
            admin_steps.pop(user_id)
            await update.message.reply_text("✅ Prix mis à jour.")
            return

        if step["step"] == "add_name":
            step["name"] = text
            step["step"] = "add_price"
            await update.message.reply_text("💰 Prix du produit ?")
            return

        if step["step"] == "add_price":
            step["price"] = float(text.replace(",", "."))
            step["step"] = "add_stock"
            await update.message.reply_text("📦 Stock initial ?")
            return

        if step["step"] == "add_stock":
            products.append({"name": step["name"], "price": step["price"], "stock": int(text)})
            save_products(products)
            admin_steps.pop(user_id)
            await update.message.reply_text("✅ Produit ajouté.")
            return

        if step["step"] == "add_admin":
            admins = load_admins()
            admins.append(int(text))
            save_admins(admins)
            admin_steps.pop(user_id)
            await update.message.reply_text("✅ Admin ajouté.")
            return

        if step["step"] == "remove_admin":
            admin_id = int(text)
            if admin_id in SUPER_ADMINS:
                await update.message.reply_text("❌ Impossible de retirer un super admin.")
                return
            admins = [a for a in load_admins() if a != admin_id]
            save_admins(admins)
            admin_steps.pop(user_id)
            await update.message.reply_text("✅ Admin retiré.")
            return

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

            orders[order_id] = {"client_id": chat_id, "cart": cart.copy(), **step_data}
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

            for admin_id in load_admins():
                await context.bot.send_message(admin_id, admin_text, reply_markup=InlineKeyboardMarkup(keyboard))

            carts[chat_id] = {}
            user_steps.pop(chat_id)
            return

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("produits", produits))
    app.add_handler(CommandHandler("panier", panier))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling(close_loop=False)
