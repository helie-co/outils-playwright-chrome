# playwright-chrome

Outil Python autonome pour piloter un navigateur Playwright visible et persistant.

L'installation modulaire place les dépendances Python, le navigateur Playwright et le profil dans le dossier de l'outil. Le profil n'utilise pas le Chrome personnel.

Exemples :

```powershell
outils playwright-chrome etat
outils playwright-chrome demarrer
outils playwright-chrome ouvrir --url https://example.com
outils playwright-chrome onglets
outils playwright-chrome capture --fichier capture.png
outils playwright-chrome arreter
```

Prototype d'enregistrement et de rejeu d'une recherche DuckDuckGo :

```powershell
outils playwright-chrome enregistrer --requete "Playwright Python"
outils playwright-chrome executer --fichier C:\Automatisations\recherche.json --fois 10 --sortie C:\Automatisations\resultats.json
```

Sans `--fichier`, le scénario est enregistré dans `scenarios\recherche.json` à l'intérieur du dossier de l'outil. Un autre nom est possible avec `--nom`; un chemin explicite reste possible avec `--fichier`. La recette est autonome : Appui/Codex n'est nécessaire que pour la concevoir ou la modifier.

Pour exporter la page courante en Markdown et JSON :

```powershell
outils playwright-chrome exporter
```

Les fichiers sont créés par défaut dans `exports\page.md` et `exports\page.json`.

Pour enregistrer un parcours réel dans Chrome :

```powershell
outils playwright-chrome enregistrer-session --nom exemple
# effectuer le parcours dans Chrome
outils playwright-chrome arreter-enregistrement
```

Le scénario est enregistré dans `scenarios\exemple.json` et peut ensuite être rejoué avec `executer`.

Les tests ne nécessitent pas de session utilisateur : `outils playwright-chrome tester`.
