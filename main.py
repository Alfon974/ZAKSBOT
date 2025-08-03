import os
import time
import threading
import sqlite3

import discord
from discord import app_commands
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

def set_xp(user_id, xp_value):
    new_xp = max(xp_value, 0)
    cursor.execute('INSERT OR IGNORE INTO users(user_id) VALUES(?)', (user_id,))
    cursor.execute('UPDATE users SET xp = ? WHERE user_id = ?', (new_xp, user_id))
    conn.commit()

def add_xp(user_id, amount):
    current = get_xp(user_id)
    set_xp(user_id, current + amount)


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
MAX_XP = 10000  # XP pour niveau 100

def xp_to_level(xp: int) -> int:
    lvl = int(xp * 99 / MAX_XP) + 1
    return min(max(lvl, 1), 100)

LEVEL_ROLES = {
    0:    "ZAKS Rookie",
    1000: "ZAKS Gamers",
    5000: "ZAKS Elite"
}

async def maybe_level_up(member: discord.Member):
    xp = get_xp(member.id)
    eligible = [lvl for lvl in LEVEL_ROLES if lvl <= xp]
    if not eligible:
        return
    target = max(eligible)
    role_name = LEVEL_ROLES[target]
    role = discord.utils.get(member.guild.roles, name=role_name)
    if role and role not in member.roles:
        try:
            for lvl, name in LEVEL_ROLES.items():
                r = discord.utils.get(member.guild.roles, name=name)
                if r and r in member.roles:
                    await member.remove_roles(r)
            await member.add_roles(role)
            log_ch = bot.get_channel(LOGS_CHANNEL_ID)
            if log_ch:
                await log_ch.send(f"🏅 {member.mention} est maintenant **{role_name}** ({xp} XP) !")
        except discord.Forbidden:
            print(f"⚠️ Pas la permission pour gérer {role_name} pour {member}.")
        except Exception as e:
            print(f"❌ Erreur maybe_level_up pour {member}: {e}")

# --- 1) Flask pour Render ---
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

# --- 2) Bot Discord et application commands tree ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command: app_commands.Command):
    log_ch = bot.get_channel(LOGS_CHANNEL_ID)
    if log_ch:
        user = interaction.user
        await log_ch.send(
            f"📩 Slash utilisé : `/{command.name}` par {user.mention} dans <#{interaction.channel.id}>"
        )

# IDs salons
WELCOME_CHANNEL_ID = 1302027297116917922
LOGS_CHANNEL_ID    = 1400141141663547462
LEVEL_LOG_CHANNEL_ID = 1401528018345787462
ADMIN_ROLE_ID      = 1302034266699599914

# --- 3) Heartbeat ---
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

# --- 4) Événements standard ---
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ {bot.user} est en ligne et slash-commands synchronisées !")
    if not heartbeat.is_running():
        heartbeat.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    add_xp(message.author.id, 10)
    await maybe_level_up(message.author)
    log_ch = bot.get_channel(LOGS_CHANNEL_ID)
    if log_ch:
        xp = get_xp(message.author.id)
        await log_ch.send(f"✉️ {message.author.mention} a gagné 10 XP (texte). Total: {xp} XP.")
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel is None and after.channel:
        set_voice_join(member.id, int(time.time()))
    elif before.channel and after.channel != before.channel:
        t0 = pop_voice_join(member.id)
        if t0:
            duration = int(time.time()) - t0
            xp_gain = duration // 60
            add_xp(member.id, xp_gain)
            await maybe_level_up(member)
            log_ch = bot.get_channel(LOGS_CHANNEL_ID)
            if log_ch:
                total = get_xp(member.id)
                await log_ch.send(f"🔊 {member.mention} a gagné {xp_gain} XP (voix). Total: {total} XP.")

# autres events (join, remove) inchangés...

# --- 5) Slash commands ---
@tree.command(name="level", description="Affiche ton XP et ton niveau")
async def slash_level(interaction: discord.Interaction):
    if interaction.channel.id != LEVEL_LOG_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ Merci d'utiliser /level dans <#{LEVEL_LOG_CHANNEL_ID}>",
            ephemeral=True
        )
        return
    xp = get_xp(interaction.user.id)
    lvl = xp_to_level(xp)
    current_thr = max([t for t in LEVEL_ROLES if t <= xp])
    next_thrs = [t for t in LEVEL_ROLES if t > xp]
    if next_thrs:
        nt = min(next_thrs);
        next_info = f"Il te manque {nt - xp} XP pour **{LEVEL_ROLES[nt]}**."
    else:
        next_info = "Niveau max atteint !"
    embed = discord.Embed(title="🎚 Progression", color=discord.Color.blurple())
    embed.set_author(name=interaction.user.display_name,
                     icon_url=interaction.user.display_avatar.url)
    embed.add_field(name="XP actuelle", value=str(xp), inline=True)
    embed.add_field(name="Niveau", value=f"{lvl} / 100", inline=True)
    embed.add_field(name="Prochain palier", value=next_info, inline=False)
    embed.set_footer(text=f"{min(xp, MAX_XP)}/{MAX_XP} XP")
    await interaction.response.send_message(embed=embed)

@tree.command(name="levelup", description="Ajoute de l'XP à un membre")
@app_commands.describe(member="Membre cible", amount="Quantité d'XP")
async def slash_levelup(interaction: discord.Interaction, member: discord.Member | None = None, amount: int = 1):
    if ADMIN_ROLE_ID not in [r.id for r in interaction.user.roles]:
        await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
        return
    member = member or interaction.user
    add_xp(member.id, amount)
    await maybe_level_up(member)
    new_xp = get_xp(member.id)
    await interaction.response.send_message(
        f"✅ {amount} XP ajouté à {member.mention}. Total: {new_xp} XP.",
        ephemeral=True
    )

@tree.command(name="leveldown", description="Retire de l'XP à un membre")
@app_commands.describe(member="Membre cible", amount="Quantité d'XP")
async def slash_leveldown(interaction: discord.Interaction, member: discord.Member | None = None, amount: int = 1):
    if ADMIN_ROLE_ID not in [r.id for r in interaction.user.roles]:
        await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
        return
    member = member or interaction.user
    current = get_xp(member.id)
    sub = min(amount, current)
    set_xp(member.id, current - sub)
    await maybe_level_up(member)
    new_xp = get_xp(member.id)
    await interaction.response.send_message(
        f"❌ {sub} XP retiré à {member.mention}. Total: {new_xp} XP.",
        ephemeral=True
    )

@tree.command(name="clearall", description="Supprime tous les messages du salon")
async def slash_clearall(interaction: discord.Interaction):
    if ADMIN_ROLE_ID not in [r.id for r in interaction.user.roles]:
        await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
        return
    # purge
    deleted = await interaction.channel.purge()
    # log
    log_ch = bot.get_channel(LOGS_CHANNEL_ID)
    if log_ch:
        await log_ch.send(f"🧹 {len(deleted)} messages supprimés dans <#{interaction.channel.id}>.")
    await interaction.response.send_message(
        f"🧹 {len(deleted)} messages supprimés.",
        ephemeral=True
    )

# --- 6) Lancement ---
def run_bot():
    print("🚀 Démarrage...")
    bot.run(os.environ['TOKEN_BOT_DISCORD'], reconnect=True)

if __name__ == "__main__":
    run_bot()
