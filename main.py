import os
import time
import threading

import discord
from discord.ext import commands, tasks
from flask import Flask

# --- 1) Flask pour Render (Web Service gratuit) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "ZAKS BOT est en ligne !"

def run_flask():
    # on masque l'avertissement de dev server
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask).start()


# --- 2) Configuration du bot Discord ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="/", intents=intents)

# Remplace par tes propres IDs
WELCOME_CHANNEL_ID = 1302027297116917922  
LOGS_CHANNEL_ID    = 1400141141663547462  


# --- 3) Heartbeat pour “rafraîchir” la présence toutes les 5 min ---
@tasks.loop(minutes=5)
async def heartbeat():
    try:
        # on remet le statut en ligne pour maintenir la connexion
        await bot.change_presence(
            status=discord.Status.online,
            activity=discord.Game("ZAKS BOT")
        )
        print("💓 Heartbeat envoyé.")
    except Exception as e:
        print(f"❌ Erreur Heartbeat : {e}")


# --- 4) Événements du bot ---
@bot.event
async def on_ready():
    print(f"✅ Connexion réussie : {bot.user} est en ligne !")
    # démarrer le heartbeat une fois connecté
    if not heartbeat.is_running():
        heartbeat.start()

@bot.event
async def on_disconnect():
    print("⚠️ Déconnexion détectée…")

@bot.event
async def on_resumed():
    print("🔄 Reconnexion Discord réussie.")

@bot.event
async def on_member_join(member):
    # message de bienvenue
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await ch.send(
            f"🎮 **Bienvenue {member.mention} sur le serveur La ZAKS !**\n\n"
            "Tu viens d’obtenir le rôle **ZAKS Rookie** 👶 — c’est le point de départ de ton aventure ici.\n\n"
            "💬 Participe aux discussions, sois présent en vocal… plus tu es actif, plus tu progresseras !\n\n"
            "🔓 Avec le temps et ton implication, tu pourras évoluer vers :\n\n"
            "🥈 **ZAKS Gamers**\n🥇 **ZAKS Elite**\n\nAmuse-toi bien ! 💥"
        )
    # attribution automatique de ZAKS Rookie
    role = discord.utils.get(member.guild.roles, name="ZAKS Rookie")
    if role:
        await member.add_roles(role)

@bot.event
async def on_member_remove(member):
    ch = bot.get_channel(LOGS_CHANNEL_ID)
    if ch:
        await ch.send(f"🚪 **{member}** a quitté le serveur.")

@bot.event
async def on_message_delete(msg):
    if msg.author.bot: return
    ch = bot.get_channel(LOGS_CHANNEL_ID)
    if ch:
        await ch.send(f"❌ Message supprimé de **{msg.author}** : `{msg.content}`")

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.content == after.content: return
    ch = bot.get_channel(LOGS_CHANNEL_ID)
    if ch:
        await ch.send(
            f"✏️ Message modifié par **{before.author}** :\n"
            f"**Avant :** {before.content}\n"
            f"**Après :** {after.content}"
        )

@bot.event
async def on_user_update(before, after):
    ch = bot.get_channel(LOGS_CHANNEL_ID)
    if ch and before.name != after.name:
        await ch.send(f"✍️ **{before}** → **{after}** (pseudo changé)")

@bot.event
async def on_guild_role_create(role):
    ch = bot.get_channel(LOGS_CHANNEL_ID)
    if ch:
        await ch.send(f"🆕 Nouveau rôle créé : **{role.name}**")

@bot.event
async def on_guild_role_delete(role):
    ch = bot.get_channel(LOGS_CHANNEL_ID)
    if ch:
        await ch.send(f"🗑 Rôle supprimé : **{role.name}**")

@bot.event
async def on_guild_role_update(b, a):
    ch = bot.get_channel(LOGS_CHANNEL_ID)
    if ch:
        await ch.send(f"♻️ Rôle modifié : **{b.name}** → **{a.name}**")

@bot.event
async def on_member_update(before, after):
    ch = bot.get_channel(LOGS_CHANNEL_ID)
    if not ch: return
    added   = set(after.roles) - set(before.roles)
    removed = set(before.roles) - set(after.roles)
    for r in added:
        await ch.send(f"✅ Rôle **{r.name}** ajouté à **{after.name}**")
    for r in removed:
        await ch.send(f"❌ Rôle **{r.name}** retiré à **{after.name}**")


# --- 5) Lancement avec auto-reconnexion et diagnostic ---
def run_bot():
    print("🚀 Tentative de connexion à Discord…")
    try:
        token = os.environ['TOKEN_BOT_DISCORD']
        bot.run(token, reconnect=True)
    except KeyError:
        print("❌ ERREUR : variable TOKEN_BOT_DISCORD introuvable.")
    except discord.LoginFailure:
        print("❌ ERREUR : token Discord invalide.")
    except Exception as e:
        print(f"❌ ERREUR INATTENDUE : {e}")

if __name__ == "__main__":
    while True:
        run_bot()
        print("⏳ Nouvelle tentative dans 5 secondes…")
        time.sleep(5)
