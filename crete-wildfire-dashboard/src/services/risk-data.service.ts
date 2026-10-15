import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { AccessResponse, FeatColl } from '../lib/types';
import { environment } from '../environments/environment';

@Injectable({
  providedIn: 'root',
})
export class RiskDataService {
  private apiUrl = environment.apiUrl;

  constructor(private http: HttpClient) {}

  getRiskZones(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/risk-zones`);
  }

  getLiveWeather(refresh = false): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/weather`, {
      params: refresh ? { refresh: 'true' } : {},
    });
  }

  getPowerLines(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/power-lines`);
  }

  getPowerNodes(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/power-nodes`);
  }

  getPowerStations(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/power-stations`);
  }

  getSettlements(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/settlements`);
  }

  getRivers(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/rivers`);
  }

  getLakes(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/lakes`);
  }

  getRoads(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/roads`);
  }

  getFireStations(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/fire-stations`);
  }

  getWaterPoints(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/water-points`);
  }

  getHelipads(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/helipads`);
  }

  getBurnedAreas(): Observable<any> {
    return this.http.get(`${this.apiUrl}/burned-areas`);
  }

  getModel(): Observable<any> {
    return this.http.get(`${this.apiUrl}/model`);
  }

  getFwi(refresh = false): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/fwi`, {
      params: refresh ? { refresh: 'true' } : {},
    });
  }

  getAccess(): Observable<AccessResponse> {
    return this.http.get<AccessResponse>(`${this.apiUrl}/access`);
  }

  getAccessProposed(points: [number, number][]): Observable<AccessResponse> {
    return this.http.get<AccessResponse>(`${this.apiUrl}/access/proposed`, {
      params: {
        p: points.map(([la, ln]) => `${la.toFixed(5)},${ln.toFixed(5)}`),
      },
    });
  }

  getAccessRoads(
    maxMin: number,
    pts: [number, number][],
  ): Observable<FeatColl> {
    const q = [
      `max_min=${maxMin}`,
      ...pts.map(([la, ln]) => `p=${la},${ln}`),
    ].join('&');
    return this.http.get<FeatColl>(`${this.apiUrl}/access/roads?${q}`);
  }
}
