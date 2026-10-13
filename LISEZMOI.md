# Texte animé — un greffon pour GIMP 3

**[English version → README.md](README.md)**

Créez des titres animés directement dans GIMP 3 : saisissez votre texte, choisissez un effet dans la galerie, puis exportez une **vidéo MP4** (avec bruitages), un **WebP animé** ou un **GIF animé**.

![La boîte de dialogue du greffon](docs/dialogue.png)

## Fonctionnalités

- **18 effets** dans une galerie avec des aperçus animés (survolez une vignette pour la lire).
- **Jusqu'à 3 écrans** à la suite, chacun avec son texte et son effet.
- **Un réglage du temps comme dans un logiciel de motion design** : animation par lettre, mot, ligne ou bloc entier ; choix de la courbe (douce, dépassement, élastique, ricochet) et de l'ordre (normal, inverse, depuis le centre, aléatoire).
- **Formats d'image prêts à l'emploi** : carré 1:1 (1080×1080), paysage 16:9 (1920×1080 ou 1280×720), portrait 9:16 (1080×1920), vertical 4:5 (1080×1350), ou personnalisé.
- **Bruitages pour le MP4** : frappe de touches, souffles, impacts, grésillement de néon… Ils sont fabriqués par le greffon lui-même : aucun fichier audio externe, donc aucune question de droits. On peut les désactiver.
- **Gestion des textes longs** : les lignes passent à la ligne automatiquement, et la taille diminue si besoin pour que le texte reste dans l'image.
- **Fenêtre d'attente** avec une grande barre de progression, une estimation du temps restant et un bouton Annuler. À la fin, un bouton ouvre le dossier qui contient le fichier.
- **Enregistrement sans mauvaise surprise** : le greffon demande avant de remplacer un fichier existant, avec la possibilité de garder les deux.
- **Interface bilingue** : en français si GIMP est en français, en anglais sinon.

## Effets

| Apparition | Mouvement | Ambiance | Spéciaux |
|---|---|---|---|
| Fondu | Chute | Néon | Tracé |
| Fondu flou | Alterné | Mise au point | Liquide (morphing) |
| Machine à écrire | Glisser | Parallaxe | Éclats |
| Rideau | Stomp | Générique | |
| Remplissage | Traînée (flou de mouvement) | Bandeau | |

| | | | |
|---|---|---|---|
| ![](docs/apercus/fondu.gif) Fondu | ![](docs/apercus/machine.gif) Machine à écrire | ![](docs/apercus/rideau.gif) Rideau | ![](docs/apercus/remplissage.gif) Remplissage |
| ![](docs/apercus/chute.gif) Chute | ![](docs/apercus/stomp.gif) Stomp | ![](docs/apercus/vitesse.gif) Traînée | ![](docs/apercus/neon.gif) Néon |
| ![](docs/apercus/focus.gif) Mise au point | ![](docs/apercus/detourage.gif) Tracé | ![](docs/apercus/liquide.gif) Liquide | ![](docs/apercus/eclats.gif) Éclats |

Quelques précisions sur les effets les plus particuliers :

- **Liquide** : quand deux écrans à la suite utilisent *Liquide*, le premier texte fond et se reforme en le second (morphing).
- **Tracé** : le greffon suit le *contour* de chaque lettre, comme un détourage animé. Il n'imite pas l'écriture à la main, qui demanderait des polices spéciales à trait unique.
- **Éclats** : cet effet est nettement plus lent à créer que les autres.

## Prérequis

- **GIMP 3.2**. Le greffon a été développé et testé avec GIMP 3.2.4 sous Windows 11. Les autres versions et les autres systèmes n'ont pas été testés.
- **ffmpeg**, uniquement pour l'export MP4. Le WebP et le GIF sont exportés par GIMP lui-même.
  - Windows : `winget install Gyan.FFmpeg`
  - macOS : `brew install ffmpeg`
  - Linux : `sudo apt install ffmpeg` (ou l'équivalent de votre distribution)

## Installation

1. Téléchargez ce dépôt (bouton vert **Code** → **Download ZIP**) et décompressez-le.
2. Copiez le dossier **`texte-anime`** en entier, avec son sous-dossier `apercus`, dans le dossier des greffons de GIMP :
   - Windows : `%APPDATA%\GIMP\3.2\plug-ins\`
   - Linux : `~/.config/GIMP/3.2/plug-ins/`
   - macOS : `~/Library/Application Support/GIMP/3.2/plug-ins/`
3. Sous Linux et macOS, rendez le script exécutable : `chmod +x texte-anime.py`
4. Relancez GIMP.

Le dossier doit garder le nom `texte-anime`, le même que celui du script. GIMP l'exige.

## Utilisation

1. **Fichier → Créer → Animation → Texte animé…**
2. Dans l'onglet **Écran 1**, saisissez votre texte. La touche Entrée crée une nouvelle ligne.
3. Cliquez sur un effet dans la galerie. Les onglets **Apparition / Mouvement / Ambiance / Spéciaux** rangent les effets.
4. Réglez l'apparence (police, taille, couleurs) et la sortie (format d'image, type de fichier, dossier, nom du fichier).
5. Cliquez sur **Valider**. Une fenêtre montre où en est la création.

### Astuces

- **N'utiliser qu'un ou deux écrans** : laissez vide le texte de l'écran 2 ou 3, ou décochez **Inclure cet écran**. Son texte est alors conservé pour plus tard. L'onglet affiche « — inactif ».
- **Réglages avancés de la durée** et **Taille personnalisée** s'ouvrent dans des bulles flottantes : la fenêtre ne change jamais de taille.
- **Nom du fichier** : tapez juste un nom, par exemple `intro`. L'extension (.mp4, .webp, .gif) est ajoutée automatiquement.
- **Couleur d'accent** : elle sert à trois effets (le volet du Rideau, le halo du Néon et le cadre de la Mise au point).
- **Survolez** un réglage pour afficher une bulle d'aide qui l'explique.

## Lire les fichiers et choisir un format

| Format | Pour l'ouvrir | Idéal pour | Limites |
|---|---|---|---|
| **MP4** | N'importe quel lecteur vidéo (Lecteur multimédia de Windows, VLC…), tous les navigateurs, toutes les plateformes vidéo | Réseaux sociaux, YouTube, montage vidéo, PowerPoint (insertion d'une vidéo) | Ne tourne pas en boucle tout seul dans une page web ou un e-mail ; dans un e-mail, c'est une pièce jointe, pas une image affichée |
| **WebP animé** | Tous les navigateurs récents (Chrome, Edge, Firefox, Safari depuis macOS Big Sur) ; des visionneuses comme XnView MP ou IrfanView (avec ses plugins) ; GIMP (ouverture en calques : **Filtres → Animation → Rejouer**) | Sites web et documentation : fichiers légers, couleurs complètes | Pas de son. L'Explorateur Windows n'affiche qu'une miniature fixe. Pas reconnu partout : Outlook sur ordinateur, certains réseaux sociaux, certaines versions de PowerPoint |
| **GIF animé** | Partout : navigateurs, visionneuses, e-mails, PowerPoint, messageries | E-mail, PowerPoint, compatibilité maximale | Pas de son. 256 couleurs seulement : les dégradés, halos et flous font des bandes visibles (Néon, Fondu flou, Liquide). Fichiers bien plus lourds que le WebP. Transparence en tout ou rien |

Le plus simple pour vérifier un WebP animé sous Windows : le glisser dans Edge ou Chrome.

## Limites connues

- **L'encodage WebP et GIF** se fait en un seul appel à GIMP. Pendant cette étape, la barre reste à 85 % et le bouton Annuler n'agit plus.
- **Le temps de création** dépend du format d'image et de l'effet : de quelques secondes à environ une minute en 1280×720. Le Fondu flou, le Tracé et les Éclats sont les plus lents.
- **Le WebP et le GIF n'ont pas de son.** Seul le MP4 peut contenir les bruitages.

## Contournements de problèmes de GIMP 3.2

Ces notes peuvent servir à d'autres auteurs de greffons :

- **Les couleurs par défaut sont perdues** à l'enregistrement d'un paramètre de couleur. Le greffon les rétablit au lancement.
- **Les paramètres de dossier font planter GIMP sous Windows** : un paramètre dossier (`GFile`) est enregistré avec des barres obliques inverses que GIMP ne sait pas relire, ce qui fait planter le lancement suivant. Le dossier est donc enregistré comme du texte simple.
- **Les polices ne sont pas forcément prêtes** quand GIMP est lancé en mode console (traitement par lots). Le greffon attend qu'elles soient chargées.
- **Remplir une sélection vide remplit tout le calque.** Chaque rectangle est limité à l'image avant d'être dessiné.
