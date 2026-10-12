# Console interactive

Depuis PowerShell : `outils playwright-chrome`.
Depuis la console `outils>` : `playwright-chrome`.

Tab complète les commandes et options. Les flèches permettent de modifier la
ligne et de retrouver les commandes précédentes. `quitter` revient à Outils.

Exemple :

```text
playwright-chrome> demarrer
playwright-chrome> enregistrement
enregistrement> demarrer --nom outlook-connection
```

Effectuez les actions manuellement dans Chromium, puis :

```text
enregistrement> arreter
enregistrement> lister
enregistrement> executer --nom outlook-connection
enregistrement> retour
playwright-chrome> quitter
```

Les anciennes commandes `enregistrer-session` et `arreter-enregistrement`
restent disponibles. Un scénario vide ne peut pas être rejoué.
Les champs password ne sont pas enregistrés.

Le mode terminal est utilisé par défaut. Pour une commande destinée à un agent :

```powershell
outils playwright-chrome lister --json
outils playwright-chrome executer --nom outlook-connection --json
```

Pour exporter la page en JSON dans un fichier, utilisez `exporter --fichier-json page.json`.
L'option `--json` est désormais exclusivement réservée au format de réponse.

Export de la page courante :

```text
exporter --format md
exporter --format json
exporter --format html
exporter
```

Sans format, les trois fichiers sont créés dans `exports/page.md`,
`exports/page.json` et `exports/page.html` (remplacés à chaque export).
Pour choisir un chemin, utilisez `--markdown CHEMIN`, `--fichier-json CHEMIN`
ou `--html CHEMIN`. Le HTML représente le DOM courant après chargement.
