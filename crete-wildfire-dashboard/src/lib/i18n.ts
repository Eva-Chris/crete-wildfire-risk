import { isDevMode } from '@angular/core';

export type Lang = 'en' | 'el';
export type Params = Record<string, string | number>;

/** English text -> Greek. Keys must match the English text in the code and templates exactly. */
const EL: Record<string, string> = {
  // ---- header ----
  'Crete wildfire risk': 'Κίνδυνος πυρκαγιάς στην Κρήτη',
  "Static susceptibility and today's Fire Weather Index":
    'Στατική ευπάθεια και ο σημερινός Δείκτης Καιρού Πυρκαγιάς',
  'Docs ↗': 'Τεκμηρίωση ↗',
  'How this tool works': 'Πώς λειτουργεί αυτό το εργαλείο',
  Dismiss: 'Κλείσιμο',

  // ---- fire weather ----
  'Fire weather': 'Καιρός πυρκαγιάς',
  'FWI for {date}': 'FWI για {date}',
  Refresh: 'Ανανέωση',
  'Refresh fire weather': 'Ανανέωση καιρού πυρκαγιάς',
  'The weather service did not answer the last refresh, so these are the last values it returned.':
    'Η υπηρεσία καιρού δεν απάντησε στην τελευταία ανανέωση, γι’ αυτό εμφανίζονται οι τελευταίες τιμές που επέστρεψε.',
  "Computing the Fire Weather Index from this season's weather. The first load can take several seconds.":
    'Υπολογισμός του Δείκτη Καιρού Πυρκαγιάς από τα δεδομένα της τρέχουσας περιόδου. Η πρώτη φόρτωση μπορεί να διαρκέσει μερικά δευτερόλεπτα.',
  '{level} (highest station)': '{level} (υψηλότερος σταθμός)',
  'Outside the usual fire season. The index is shown for reference only.':
    'Εκτός της συνήθους αντιπυρικής περιόδου. Ο δείκτης εμφανίζεται μόνο ενδεικτικά.',
  "Canadian Fire Weather Index at noon, with the next days after the arrows. It describes today's weather danger and does not change the susceptibility scores. Zone popups show the nearest station.":
    'Καναδικός Δείκτης Καιρού Πυρκαγιάς το μεσημέρι, με τις επόμενες ημέρες μετά τα βέλη. Περιγράφει τον σημερινό κίνδυνο λόγω καιρού και δεν αλλάζει τη βαθμολογία ευπάθειας. Τα αναδυόμενα παράθυρα των ζωνών δείχνουν τον πλησιέστερο σταθμό.',
  'Fire Weather Index unavailable. Check that the API is running.':
    'Ο Δείκτης Καιρού Πυρκαγιάς δεν είναι διαθέσιμος. Ελέγξτε ότι το API εκτελείται.',
  'Fire Weather Index': 'Δείκτης Καιρού Πυρκαγιάς',

  // ---- drive-time coverage ----
  'Distance measure': 'Τρόπος μέτρησης απόστασης',
  'By road': 'Οδικώς',
  'Straight line': 'Ευθεία γραμμή',
  'Drive time': 'Χρόνος οδήγησης',
  '{gaps} of {high} high or very high risk zones cannot be reached by road from a fire station within {min} minutes.':
    '{gaps} από {high} ζώνες υψηλού ή πολύ υψηλού κινδύνου δεν είναι προσβάσιμες οδικώς από πυροσβεστικό σταθμό εντός {min} λεπτών.',
  'Dashed outlines on the map mark those zones. Drive times follow public roads at assumed fire-engine speeds and exclude call handling and crew turnout. A zone with no road within {m} m counts as not reached.':
    'Τα διακεκομμένα περιγράμματα στον χάρτη επισημαίνουν αυτές τις ζώνες. Οι χρόνοι οδήγησης ακολουθούν τους δημόσιους δρόμους με υποθετικές ταχύτητες πυροσβεστικών οχημάτων και δεν περιλαμβάνουν την παραλαβή της κλήσης και την ετοιμασία του πληρώματος. Μια ζώνη χωρίς δρόμο σε απόσταση {m} m θεωρείται μη προσβάσιμη.',
  'High or very high risk forest within 1 km of each settlement centre. Covered means a fire station within {min} minutes by road, including proposed stations.':
    'Δάσος υψηλού ή πολύ υψηλού κινδύνου σε απόσταση έως 1 km από το κέντρο κάθε οικισμού. «Καλυμμένος» σημαίνει πυροσβεστικός σταθμός σε απόσταση έως {min} λεπτά οδικώς, συμπεριλαμβανομένων των προτεινόμενων σταθμών.',
  'Drive time to nearest station': 'Χρόνος οδήγησης έως τον πλησιέστερο σταθμό',
  'Status at {min} min': 'Κατάσταση στα {min} λεπτά',
  'Drive time (min)': 'Χρόνος οδήγησης (min)',
  'Drive time limit (min)': 'Όριο χρόνου οδήγησης (min)',
  'Drive times along OpenStreetMap roads at assumed fire-engine speeds. High risk = top two percentile classes of the score.':
    'Χρόνοι οδήγησης σε δρόμους του OpenStreetMap με υποθετικές ταχύτητες πυροσβεστικών οχημάτων. Υψηλός κίνδυνος = οι δύο ανώτερες εκατοστημοριακές κατηγορίες του δείκτη.',
  'A proposed station is more than 500 m from the nearest road, so its drive times include a slow off-road leg.':
    'Ένας προτεινόμενος σταθμός απέχει πάνω από 500 m από τον πλησιέστερο δρόμο, επομένως οι χρόνοι του περιλαμβάνουν ένα αργό τμήμα εκτός δρόμου.',
  'Could not compute drive times for the proposed stations.':
    'Δεν ήταν δυνατός ο υπολογισμός χρόνων οδήγησης για τους προτεινόμενους σταθμούς.',

  '>{n} min': '>{n} λεπτά',
  '{n} min': '{n} λεπτά',
  '{n} km': '{n} χλμ',

  // weather station names
  Chania: 'Χανιά',
  Sfakia: 'Σφακιά',
  Rethymno: 'Ρέθυμνο',
  Heraklion: 'Ηράκλειο',
  Messara: 'Μεσαρά',
  'Agios Nikolaos': 'Άγιος Νικόλαος',
  Ierapetra: 'Ιεράπετρα',
  Sitia: 'Σητεία',

  // ---- risk and FWI classes (neuter, to match the docs page) ----
  'Very high': 'Πολύ υψηλό',
  High: 'Υψηλό',
  Moderate: 'Μέτριο',
  Low: 'Χαμηλό',
  'Very low': 'Πολύ χαμηλό',
  Extreme: 'Ακραίο',

  // ---- legend ----
  'Color zones by': 'Χρωματισμός ζωνών κατά',
  'Total risk score': 'Συνολικός δείκτης κινδύνου',
  'Fuel (land cover)': 'Καύσιμη ύλη (κάλυψη γης)',
  Slope: 'Κλίση εδάφους',
  Aspect: 'Προσανατολισμός',
  'Aspect (SW-facing)': 'Προσανατολισμός (νοτιοδυτικός)',
  'Fire history': 'Ιστορικό πυρκαγιών',
  'Close to power grid': 'Εγγύτητα σε δίκτυο ηλεκτροδότησης',
  'Close to roads': 'Εγγύτητα σε οδικό δίκτυο',
  'Next to settlements (WUI)': 'Γειτνίαση με οικισμούς (WUI)',
  'How readily the CORINE land cover in the zone burns.':
    'Πόσο εύκολα καίγεται η κάλυψη γης CORINE της ζώνης.',
  'Mean slope, steeper scores higher.':
    'Μέση κλίση· οι πιο απότομες πλαγιές βαθμολογούνται υψηλότερα.',
  'How much of the zone faces the hot, dry south-west.':
    'Πόσο μέρος της ζώνης έχει νοτιοδυτικό προσανατολισμό (θερμό και ξηρό).',
  'Closer to power lines scores higher (2 km cap).':
    'Όσο πιο κοντά σε γραμμές ρεύματος, τόσο υψηλότερη η βαθμολογία (όριο 2 km).',
  'Closer to roads scores higher (1 km cap).':
    'Όσο πιο κοντά σε δρόμους, τόσο υψηλότερη η βαθμολογία (όριο 1 km).',
  'Zone borders a settlement: 100, otherwise 0.':
    'Η ζώνη συνορεύει με οικισμό: 100, διαφορετικά 0.',
  'Select a class to hide or show it on the map.':
    'Επιλέξτε μια κατηγορία για να την αποκρύψετε ή να την εμφανίσετε στον χάρτη.',
  'Show this class': 'Εμφάνιση αυτής της κατηγορίας',
  'Hide this class': 'Απόκρυψη αυτής της κατηγορίας',
  'factor score': 'βαθμολογία παράγοντα',

  // ---- response coverage ----
  'Response coverage': 'Κάλυψη ανταπόκρισης',
  '{pct}% of high-risk zones uncovered':
    '{pct}% των ζωνών υψηλού κινδύνου χωρίς κάλυψη',
  'Fire station reach': 'Εμβέλεια πυροσβεστικών σταθμών',
  'Response radius': 'Ακτίνα ανταπόκρισης',
  '+ Add proposed station': '+ Προσθήκη προτεινόμενου σταθμού',
  'Click the map to place…': 'Κάντε κλικ στον χάρτη για τοποθέτηση…',
  'Clear ({n})': 'Εκκαθάριση ({n})',
  'Proposed stations cover {n} more high-risk zones ({was} → {now} uncovered).':
    'Οι προτεινόμενοι σταθμοί καλύπτουν {n} ακόμη ζώνες υψηλού κινδύνου ({was} → {now} χωρίς κάλυψη).',
  '{gaps} of {high} high or very high risk zones are farther than {km} km from a fire station.':
    '{gaps} από {high} ζώνες υψηλού ή πολύ υψηλού κινδύνου απέχουν περισσότερο από {km} km από πυροσβεστικό σταθμό.',
  'Dashed outlines on the map mark those zones. Distances are straight-line, not by road.':
    'Τα διακεκομμένα περιγράμματα στον χάρτη επισημαίνουν αυτές τις ζώνες. Οι αποστάσεις είναι σε ευθεία γραμμή, όχι οδικές.',
  'Waiting for station data. If this stays, restart the API so it adds distances to the zones.':
    'Αναμονή δεδομένων σταθμών. Αν παραμένει έτσι, επανεκκινήστε το API ώστε να προσθέσει τις αποστάσεις στις ζώνες.',
  'Proposed station (drag to move, click to remove)':
    'Προτεινόμενος σταθμός (σύρετε για μετακίνηση, κλικ για αφαίρεση)',

  // ---- settlement exposure ----
  'Settlement exposure': 'Έκθεση οικισμών',
  '{n} exposed': '{n} εκτεθειμένοι',
  'High or very high risk forest within 1 km of each settlement centre. Covered means a fire station within {km} km in a straight line, including proposed stations.':
    'Δάσος υψηλού ή πολύ υψηλού κινδύνου σε απόσταση έως 1 km από το κέντρο κάθε οικισμού. «Καλυμμένος» σημαίνει πυροσβεστικός σταθμός σε ακτίνα {km} km σε ευθεία γραμμή, συμπεριλαμβανομένων των προτεινόμενων σταθμών.',
  'Uncovered only': 'Μόνο ακάλυπτοι',
  'Export CSV': 'Εξαγωγή CSV',
  'Export Excel': 'Εξαγωγή Excel',
  covered: 'καλυμμένος',
  uncovered: 'ακάλυπτος',
  'Show top 20': 'Εμφάνιση των 20 πρώτων',
  'Show all': 'Εμφάνιση όλων',

  // ---- burned areas ----
  'Burned areas': 'Καμένες εκτάσεις',
  '{shown} of {total} fires': '{shown} από {total} πυρκαγιές',
  From: 'Από',
  To: 'Έως',
  'All years': 'Όλα τα έτη',
  'After {y} only': 'Μόνο μετά το {y}',
  'Up to {y} (used to build fire history)':
    'Έως {y} (χρησιμοποιήθηκαν για το ιστορικό πυρκαγιών)',
  'After {y} (used to test the model)':
    'Μετά το {y} (χρησιμοποιήθηκαν για τον έλεγχο του μοντέλου)',

  // ---- layers ----
  Layers: 'Επίπεδα',
  Risk: 'Κίνδυνος',
  'Firefighting resources': 'Πυροσβεστικά μέσα',
  'Power grid': 'Δίκτυο ηλεκτροδότησης',
  'Settlements and access': 'Οικισμοί και πρόσβαση',
  Water: 'Νερό',
  Weather: 'Καιρός',
  'Forest risk zones': 'Δασικές ζώνες κινδύνου',
  'Transmission lines': 'Γραμμές μεταφοράς',
  'Pylons and nodes': 'Πυλώνες και κόμβοι',
  Substations: 'Υποσταθμοί',
  Settlements: 'Οικισμοί',
  'Road network': 'Οδικό δίκτυο',
  Rivers: 'Ποτάμια',
  Lakes: 'Λίμνες',
  'Wind at stations': 'Άνεμος στους σταθμούς',
  'Fire stations': 'Πυροσβεστικοί σταθμοί',
  Helipads: 'Ελικοδρόμια',
  'Hydrants and water wells': 'Πυροσβεστικοί κρουνοί και γεωτρήσεις',
  'Burned areas (EFFIS)': 'Καμένες εκτάσεις (EFFIS)',

  // ---- map style, toolbar, footer ----
  'Map style': 'Στυλ χάρτη',
  Terrain: 'Ανάγλυφο',
  Satellite: 'Δορυφορικός',
  'Risk layer opacity': 'Αδιαφάνεια επιπέδου κινδύνου',
  'Hide panel': 'Απόκρυψη πάνελ',
  'Show panel': 'Εμφάνιση πάνελ',
  'Fit Crete': 'Προσαρμογή στην Κρήτη',
  'Fit Crete in view': 'Προσαρμογή της Κρήτης στην προβολή',
  'Loading forest zones for Crete': 'Φόρτωση δασικών ζωνών της Κρήτης',
  'Zone colours show a static susceptibility score. Classes are percentile bands across all zones, so they show relative ranking, not an absolute danger level. Fire Weather Index calculated from weather data by Open-Meteo.com. Land cover: Contains Copernicus Land Monitoring Service information, © European Union, EEA, CORINE Land Cover 2012.':
    'Τα χρώματα των ζωνών δείχνουν έναν στατικό δείκτη ευπάθειας. Οι κατηγορίες είναι εκατοστημοριακές ζώνες σε όλες τις ζώνες, επομένως δείχνουν σχετική κατάταξη και όχι απόλυτο επίπεδο κινδύνου. Ο Δείκτης Καιρού Πυρκαγιάς υπολογίζεται από δεδομένα καιρού του Open-Meteo.com. Κάλυψη γης: Περιλαμβάνει πληροφορίες της υπηρεσίας Copernicus Land Monitoring Service, © Ευρωπαϊκή Ένωση, EEA, CORINE Land Cover 2012.',

  // ---- errors ----
  'Could not load /api/model. Using default class breaks.':
    'Δεν ήταν δυνατή η φόρτωση του /api/model. Χρησιμοποιούνται τα προεπιλεγμένα όρια κατηγοριών.',
  'Could not reach the weather service. Check that the API is running and can reach the internet.':
    'Δεν ήταν δυνατή η επικοινωνία με την υπηρεσία καιρού. Ελέγξτε ότι το API εκτελείται και έχει πρόσβαση στο διαδίκτυο.',
  'Could not load the Fire Weather Index. Check the API console.':
    'Δεν ήταν δυνατή η φόρτωση του Δείκτη Καιρού Πυρκαγιάς. Ελέγξτε την κονσόλα του API.',
  'Could not load "{name}". Check the API console for details.':
    'Δεν ήταν δυνατή η φόρτωση του επιπέδου «{name}». Ελέγξτε την κονσόλα του API για λεπτομέρειες.',

  // ---- popups ----
  Substation: 'Υποσταθμός',
  Settlement: 'Οικισμός',
  'Fire station': 'Πυροσβεστικός σταθμός',
  Helipad: 'Ελικοδρόμιο',
  'Fire hydrant': 'Πυροσβεστικός κρουνός',
  'Water well': 'Γεώτρηση',
  'No attributes in the file.': 'Δεν υπάρχουν χαρακτηριστικά στο αρχείο.',
  Temperature: 'Θερμοκρασία',
  Humidity: 'Υγρασία',
  Wind: 'Άνεμος',
  from: 'από',
  'not available': 'μη διαθέσιμο',
  'relative susceptibility: {level}': 'σχετική ευπάθεια: {level}',
  'Why this score': 'Γιατί αυτή η βαθμολογία',
  'Unexplained difference': 'Ανεξήγητη διαφορά',
  'Sum of factors': 'Άθροισμα παραγόντων',
  'scored {s}/100': 'βαθμολογία {s}/100',
  '{pct}% of score': '{pct}% της βαθμολογίας',
  'Fire weather today · {name} station':
    'Καιρός πυρκαγιάς σήμερα · σταθμός {name}',
  'Fine fuel dryness (FFMC)': 'Ξηρότητα λεπτής καύσιμης ύλης (FFMC)',
  'Drought code (DC)': 'Δείκτης ξηρασίας (DC)',
  'Weather is shown separately and does not change the score above.':
    'Ο καιρός εμφανίζεται ξεχωριστά και δεν αλλάζει την παραπάνω βαθμολογία.',
  Zone: 'Ζώνη',
  'Mean elevation': 'Μέσο υψόμετρο',
  'High-risk forest within 1 km': 'Δάσος υψηλού κινδύνου σε ακτίνα 1 km',
  'Nearest fire station': 'Πλησιέστερος πυροσβεστικός σταθμός',
  'Status at {km} km': 'Κατάσταση στα {km} km',
  'land cover unknown': 'άγνωστη κάλυψη γης',
  'mixed or mostly flat': 'μικτός ή κυρίως επίπεδος',
  Yes: 'Ναι',
  No: 'Όχι',

  // ---- Excel export ----
  Latitude: 'Γεωγραφικό πλάτος',
  Longitude: 'Γεωγραφικό μήκος',
  'High-risk forest within 1 km (ha)':
    'Δάσος υψηλού κινδύνου σε ακτίνα 1 km (ha)',
  'Share of 1 km circle (%)': 'Ποσοστό κύκλου 1 km (%)',
  'Nearest station (km)': 'Πλησιέστερος σταθμός (km)',
  Covered: 'Καλυμμένος',
  yes: 'ναι',
  no: 'όχι',
  Exposure: 'Έκθεση',
  Scenario: 'Σενάριο',
  Exported: 'Εξαγωγή',
  Scoring: 'Βαθμολόγηση',
  'Static susceptibility score (no weather adjustment)':
    'Στατικός δείκτης ευπάθειας (χωρίς προσαρμογή για τον καιρό)',
  'Coverage radius (km)': 'Ακτίνα κάλυψης (km)',
  'Proposed stations': 'Προτεινόμενοι σταθμοί',
  Note: 'Σημείωση',
  'Straight-line distances. High risk = top two percentile classes of the score.':
    'Αποστάσεις σε ευθεία γραμμή. Υψηλός κίνδυνος = οι δύο ανώτερες εκατοστημοριακές κατηγορίες του δείκτη.',

  // ---- CORINE class names (the dominant class shown in zone popups) ----
  'Continuous urban': 'Συνεχής αστικός ιστός',
  'Urban fabric': 'Αστικός ιστός',
  'Industrial / commercial': 'Βιομηχανικές / εμπορικές εκτάσεις',
  Mines: 'Χώροι εξόρυξης',
  'Dump sites': 'Χώροι απόθεσης απορριμμάτων',
  'Construction sites': 'Εργοτάξια',
  'Green urban areas': 'Αστικό πράσινο',
  'Sport and leisure': 'Αθλητικές εγκαταστάσεις και αναψυχή',
  'Arable land': 'Αρόσιμη γη',
  Vineyards: 'Αμπελώνες',
  'Fruit orchards': 'Οπωρώνες',
  'Olive groves': 'Ελαιώνες',
  Pastures: 'Βοσκοτόποι',
  'Annual + permanent crops': 'Ετήσιες και μόνιμες καλλιέργειες',
  'Complex cultivation': 'Σύνθετα συστήματα καλλιέργειας',
  'Agriculture with natural vegetation': 'Γεωργία με φυσική βλάστηση',
  'Broadleaf forest': 'Δάσος πλατύφυλλων',
  'Conifer forest': 'Δάσος κωνοφόρων',
  'Mixed forest': 'Μικτό δάσος',
  'Natural grassland': 'Φυσικοί βοσκότοποι',
  Heathland: 'Ρείκη και χέρσα βλάστηση',
  'Maquis / sclerophyllous scrub': 'Μακί / σκληρόφυλλη βλάστηση',
  'Transitional woodland-scrub': 'Μεταβατικές δασώδεις-θαμνώδεις εκτάσεις',
  'Beaches and dunes': 'Παραλίες και θίνες',
  'Bare rock': 'Γυμνοί βράχοι',
  'Sparse vegetation': 'Αραιή βλάστηση',
  'Burnt area': 'Καμένη έκταση',
  'Inland marsh': 'Εσωτερικά έλη',
  'Water bodies': 'Υδάτινες μάζες',
};

const COMPASS_EL: Record<string, string> = {
  N: 'Β',
  NE: 'ΒΑ',
  E: 'Α',
  SE: 'ΝΑ',
  S: 'Ν',
  SW: 'ΝΔ',
  W: 'Δ',
  NW: 'ΒΔ',
};

/** Strings with numbers or names inside that the plain dictionary cannot hold. */
const RULES: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^([\d.]+) and above$/, (m) => `${m[1]} και άνω`],
  [/^([\d.]+) to ([\d.]+)$/, (m) => `${m[1]} έως ${m[2]}`],
  [/^below ([\d.]+)$/, (m) => `κάτω από ${m[1]}`],
  [/^faces (N|NE|E|SE|S|SW|W|NW)$/, (m) => `βλέπει προς ${COMPASS_EL[m[1]]}`],
  [/^~(\d+)% burned$/, (m) => `~${m[1]}% καμένο`],
  [
    /^(power line|road) touches the zone$/,
    (m) =>
      m[1] === 'road'
        ? 'ο δρόμος αγγίζει τη ζώνη'
        : 'η γραμμή ρεύματος αγγίζει τη ζώνη',
  ],
  [/^(.+), (\d+)% of zone$/, (m) => `${EL[m[1]] ?? m[1]}, ${m[2]}% της ζώνης`],
  [
    /^Share of the zone burned up to (\d+)\.$/,
    (m) => `Ποσοστό της ζώνης που κάηκε έως το ${m[1]}.`,
  ],
];

function fromRules(text: string): string | undefined {
  for (const [re, fn] of RULES) {
    const m = text.match(re);
    if (m) return fn(m);
  }
  return undefined;
}

const warned = new Set<string>();

/**
 * Translates an English UI string and fills {placeholders}.
 * Unknown text is returned unchanged; in dev mode it is also logged once (console level "Verbose").
 */
export function translate(lang: string, text: string, params?: Params): string {
  let out = text;
  if (lang === 'el') {
    out = EL[text] ?? fromRules(text) ?? text;
    if (
      out === text &&
      isDevMode() &&
      /[A-Za-z]{3,}/.test(text) &&
      !warned.has(text)
    ) {
      warned.add(text);
      console.debug('[i18n] no Greek text for:', text);
    }
  }
  return params
    ? out.replace(/\{(\w+)\}/g, (_, k) => String(params[k] ?? `{${k}}`))
    : out;
}
