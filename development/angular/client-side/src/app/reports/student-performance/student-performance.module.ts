import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Routes } from '@angular/router';
import { AuthGuard } from 'src/app/auth.guard';
import { PATReportComponent } from './pat-report/pat-report.component';
import { SemViewComponent } from './sem-view/sem-view.component';
import { FormsModule } from '@angular/forms';
import { HeatChartComponent } from './heat-chart/heat-chart.component';

const performRoute: Routes = [
  {
    path: '', canActivate: [AuthGuard], children: [
      {
        path: 'semester-report', component: SemViewComponent, canActivateChild: [AuthGuard]
      },
      {
        path: 'pat-report', component: PATReportComponent, canActivateChild: [AuthGuard]
      },
      {
        path: 'heat-chart', component: HeatChartComponent, canActivateChild: [AuthGuard]
      }
    ]
  }
]

@NgModule({
  declarations: [
    SemViewComponent,
    PATReportComponent,
    HeatChartComponent
  ],
  imports: [
    CommonModule,
    FormsModule,
    RouterModule.forChild(performRoute)
  ]
})
export class StudentPerformanceModule { }
