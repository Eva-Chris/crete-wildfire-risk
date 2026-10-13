import { Routes } from '@angular/router';
import { DocsComponent } from '../components/docs/docs.component';
import { MapComponent } from '../components/map/map.component';

export const routes: Routes = [
  { path: '', component: MapComponent },
  { path: 'docs', component: DocsComponent },
  { path: '**', redirectTo: '' },
];
