import os
import time
import threading
import sqlite3

import discord
from discord.ext import commands, tasks
from flask import Flask

# --- 0) Base de données SQLite pour l'XP ---
conn = sqlite3.connect('xp.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    xp INTEGER DEFAULT 0,
    last_voice_join INTEGER
)
''')
conn.commit()

def get_xp(user_id):
    cursor.execute('SELECT xp FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

def add_xp(user_id, amount):
    cursor.execute('INSERT OR IGNORE INTO users(user_id) VALUES(?)', (user_id,))
    cursor.execute('UPDATE users SET xp = xp + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()

def set_voice_join(user_id, timestamp):
    cursor.execute('INSERT OR IGNORE INTO users(user_id) VALUES(?)', (user_id,))
    cursor.execute('UPDATE users SET last_voice_join = ? WHERE user_id = ?', (timestamp, user_id))
    conn.commit()

def pop_voice_join(user_id):
    cursor.execute('SELECT last_voice_join FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    t0 = row[0]
    cursor.execute('UPDATE users SET last_voice_join = NULL WHERE user_id = ?', (user_id,))
    conn.commit()
    return t0

# --- Paliers d’XP et conversion vers niveau [1-100] ---
MAX_XP = 10000  # XP nécessaire pour atteindre le niveau 100

def xp_to_level(xp: int) -> int:
    """
    Conversion linéaire de l'XP [0…MAX_XP] vers un niveau [1…100].
    Si xp dépasse MAX_XP, on reste niveau 100.
    """
    lvl = int(xp * 99 / MAX_XP) + 1
    return min(max(lvl, 1), 100)

# Dictionnaire palier -> nom de rôle
LEVEL_ROLES = {
    0:    "ZAKS Rookie",
    1000: "ZAKS Gamers",
    5000: "ZAKS Elite"
}

async def maybe_level_up(member):
    xp = get_xp(member.id)
    eligible = [lvl for lvl in LEVEL_ROLES if lvl <= xp]
    if not eligible:
        return
    target = max(eligible)
    role_name = LEVEL_ROLES[target]
    role = discord.utils.get(member.guild.roles, name=role_name)
    if role and role not in member.roles:
        # retirer anciens rôles
        for lvl, name in LEVEL_ROLES.items():
            r = discord.utils.get(member.guild.roles, name=name)
            if r and r in member.roles:
                await member.remove_roles(r)
        # ajouter le nouveau rôle
        await member.add_roles(role)
        logs = bot.get_channel(LOGS_CHANNEL_ID)
        if logs:
            await logs.send(f"🏅 {member.mention} est maintenant **{role_name}** ({xp} XP) !")

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
bot = commands.Bot(command_prefix="!", intents=intents)

# Remplace par tes propres IDs
WELCOME_CHANNEL_ID = 1302027297116917922  
LOGS_CHANNEL_ID    = 1400141141663547462  

# --- 3) Heartbeat toutes les 5 min ---
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

# --- 4) Événements du bot ---
@bot.event
async def on_ready():
    print(f"✅ Connexion réussie : {bot.user} est en ligne !")
    if not heartbeat.is_running():
        heartbeat.start()

@bot.event
async def on_disconnect():
    print("⚠️ Déconnexion détectée…")

@bot.event
async def on_resumed():
    print("🔄 Reconnexion Discord réussie.")

# XP sur message texte
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    add_xp(message.author.id, 10)
    await maybe_level_up(message.author)
    await bot.process_commands(message)

# XP sur temps en vocal
@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel is None and after.channel:
        set_voice_join(member.id, int(time.time()))
    elif before.channel and after.channel != before.channel:
        t0 = pop_voice_join(member.id)
        if t0:
            duration = int(time.time()) - t0
            xp_gain = duration // 60  # 1 XP par minute
            add_xp(member.id, xp_gain)
            ch = bot.get_channel(WELCOME_CHANNEL_ID)
            if ch:
                await ch.send(f"🗣️ {member.mention} gagne {xp_gain} XP (voix) !")
            await maybe_level_up(member)

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

# --- Commande /level pour consulter XP et niveau ---
@bot.command(name="level")
async def level_cmd(ctx, member: discord.Member = None):
    """Affiche l'XP et le niveau (1–100) d'un membre."""
    member = member or ctx.author
    xp = get_xp(member.id)
    lvl = xp_to_level(xp)

    embed = discord.Embed(
        title="🎚 Statut de progression",
        color=discord.Color.blurple()
    )
    embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else None)
    embed.add_field(name="XP actuelle", value=f"{xp}", inline=True)
    embed.add_field(name="Niveau", value=f"{lvl} / 100", inline=True)
    embed.set_footer(text=f"Barre de progression : {min(xp, MAX_XP)} / {MAX_XP} XP")
    await ctx.send(embed=embed)

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

