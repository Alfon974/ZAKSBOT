print(">>> DEBUT DU SCRIPT main.py !")
import os
import time
import threading
import json
import asyncio

import discord
from discord.ext import commands, tasks
from flask import Flask
from discord import app_commands

# --- 1) Flask pour Render (Web Service gratuit) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "ZAKS BOT est en ligne !"

def run_flask():
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask).start()

# --- 2) Configuration du bot Discord ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="/", intents=intents)

# Remplace par tes propres IDs
GUILD_ID = 1057336035325005875
WELCOME_CHANNEL_ID = 1302027297116917922
LOGS_CHANNEL_ID = 1400141141663547462
LEVEL_LOG_CHANNEL_ID = 1401528018345787462

# --- 3) XP & Niveaux ---
XP_FILE = "data_xp.json"
XP_MIN = 0
XP_MAX = 10000
LEVEL_MIN = 1
LEVEL_MAX = 100

ROLES_BY_LEVEL = [
    (1, "ZAKS Rookie"),
    (30, "ZAKS Gamer"),
    (70, "ZAKS Elite")
]

def load_xp():
    if not os.path.exists(XP_FILE):
        with open(XP_FILE, "w") as f:
            f.write("{}")
    with open(XP_FILE, "r") as f:
        return json.load(f)

def save_xp(data):
    with open(XP_FILE, "w") as f:
        json.dump(data, f, indent=2)

def xp_to_level(xp):
    level = min(LEVEL_MAX, max(LEVEL_MIN, int(xp / (XP_MAX // (LEVEL_MAX - LEVEL_MIN + 1)) + 1)))
    return level

def level_to_role(level):
    result = ROLES_BY_LEVEL[0][1]
    for lvl, role in ROLES_BY_LEVEL:
        if level >= lvl:
            result = role
    return result

async def set_user_role(member, level):
    role_name = level_to_role(level)
    guild = member.guild
    to_add = discord.utils.get(guild.roles, name=role_name)
    roles_to_remove = [discord.utils.get(guild.roles, name=role) for _, role in ROLES_BY_LEVEL if role != role_name]
    if to_add and to_add not in member.roles:
        await member.add_roles(to_add)
    for r in roles_to_remove:
        if r and r in member.roles:
            await member.remove_roles(r)

async def add_xp(member, amount, logs_channel, reason="activité"):
    data = load_xp()
    uid = str(member.id)
    before_xp = data.get(uid, {}).get("xp", 0)
    before_level = xp_to_level(before_xp)
    xp = max(XP_MIN, min(XP_MAX, before_xp + amount))
    data[uid] = {"xp": xp}
    after_level = xp_to_level(xp)
    save_xp(data)
    # Changement de niveau ?
    if after_level != before_level:
        await set_user_role(member, after_level)
        await logs_channel.send(
            f"🔔 {member.mention} passe du niveau **{before_level}** à **{after_level}** grâce à son {reason} !"
        )
    else:
        await logs_channel.send(
            f"➕ {member.mention} gagne {amount} XP ({reason}), total : {xp} XP (niveau {after_level})"
        )
    return xp, after_level

async def remove_xp(member, amount, logs_channel, reason="modération"):
    return await add_xp(member, -abs(amount), logs_channel, reason)

# --- 4) Heartbeat & tâches XP ---
@tasks.loop(minutes=5)
async def heartbeat():
    try:
        await bot.change_presence(
            status=discord.Status.online,
            activity=discord.Game("ZAKS BOT")
        )
        print("💓 Heartbeat envoyé.")
    except Exception as e:
        print(f"❌ Erreur Heartbeat : {e}")

@tasks.loop(minutes=1)
async def xp_voice_task():
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot:
                    logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
                    await add_xp(member, 2, logs_channel, reason="présence vocale")

# --- 5) Événements du bot ---
@bot.event
async def on_ready():
    print(f"✅ Connexion réussie : {bot.user} est en ligne !")
    if not heartbeat.is_running():
        heartbeat.start()
    if not xp_voice_task.is_running():
        xp_voice_task.start()
    # Synchronisation des commandes
    try:
        await tree.sync(guild=discord.Object(id=GUILD_ID))
        print("✅ Commandes slash synchronisées !")
    except Exception as e:
        print("❌ Erreur sync commandes :", e)

@bot.event
async def on_disconnect():
    print("⚠️ Déconnexion détectée…")

@bot.event
async def on_resumed():
    print("🔄 Reconnexion Discord réussie.")

@bot.event
async def on_member_join(member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await ch.send(
            f"🎮 **Bienvenue {member.mention} sur le serveur La ZAKS !**\n\n"
            "Tu viens d’obtenir le rôle **ZAKS Rookie** 👶 — c’est le point de départ de ton aventure ici.\n\n"
            "💬 Participe aux discussions, sois présent en vocal… plus tu es actif, plus tu progresseras !\n\n"
            "🔓 Avec le temps et ton implication, tu pourras évoluer vers :\n\n"
            "🥈 **ZAKS Gamers**\n🥇 **ZAKS Elite**\n\nAmuse-toi bien ! 💥"
        )
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

# XP automatique sur message texte
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.guild:
        logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
        await add_xp(message.author, 5, logs_channel, reason="message texte")
    await bot.process_commands(message)

# --- 6) Commandes Slash ---
tree = app_commands.CommandTree(bot)

@tree.command(name="clearall", description="Supprime tous les messages du salon (admin seulement)")
@app_commands.checks.has_role("Admin")
async def clearall(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Tu n'as pas le droit d'utiliser cette commande.", ephemeral=True)
        return
    channel = interaction.channel
    deleted = await channel.purge(limit=None)
    logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
    await logs_channel.send(f"🧹 {interaction.user.mention} a supprimé {len(deleted)} messages dans {channel.mention}")
    await interaction.response.send_message(f"Tous les messages supprimés !", ephemeral=True)

@tree.command(name="level", description="Affiche ton niveau")
async def level(interaction: discord.Interaction):
    if interaction.channel.id != LEVEL_LOG_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ Utilise cette commande dans <#{LEVEL_LOG_CHANNEL_ID}> !", ephemeral=True
        )
        return
    data = load_xp()
    uid = str(interaction.user.id)
    xp = data.get(uid, {}).get("xp", 0)
    level = xp_to_level(xp)
    await interaction.response.send_message(
        f"{interaction.user.mention} | XP : **{xp}** | Niveau : **{level}** | Rôle : **{level_to_role(level)}**"
    )

@tree.command(name="levelup", description="Ajoute de l'XP à un membre (admin seulement)")
@app_commands.describe(member="Membre à modifier", xp="Quantité d'XP à ajouter")
@app_commands.checks.has_role("Admin")
async def levelup(interaction: discord.Interaction, member: discord.Member, xp: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Tu n'as pas le droit d'utiliser cette commande.", ephemeral=True)
        return
    logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
    await add_xp(member, xp, logs_channel, reason=f"commande admin /levelup par {interaction.user}")
    await interaction.response.send_message(f"{member.mention} a gagné {xp} XP !", ephemeral=True)

@tree.command(name="leveldown", description="Retire de l'XP à un membre (admin seulement)")
@app_commands.describe(member="Membre à modifier", xp="Quantité d'XP à retirer")
@app_commands.checks.has_role("Admin")
async def leveldown(interaction: discord.Interaction, member: discord.Member, xp: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Tu n'as pas le droit d'utiliser cette commande.", ephemeral=True)
        return
    logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
    await remove_xp(member, xp, logs_channel, reason=f"commande admin /leveldown par {interaction.user}")
    await interaction.response.send_message(f"{member.mention} a perdu {xp} XP.", ephemeral=True)

# --- 7) Lancement avec auto-reconnexion et diagnostic ---
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

