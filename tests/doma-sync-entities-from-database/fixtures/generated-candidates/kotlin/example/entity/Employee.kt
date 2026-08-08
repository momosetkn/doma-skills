package example.entity

import org.seasar.doma.Column
import org.seasar.doma.Entity
import org.seasar.doma.GeneratedValue
import org.seasar.doma.GenerationType
import org.seasar.doma.Id
import org.seasar.doma.Metamodel
import org.seasar.doma.Table
import org.seasar.doma.Version

/** Employees */
@Entity(metamodel = Metamodel())
@Table(schema = "public", name = "employee")
class Employee {

    /** Employee ID */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "employee_id")
    var id: Int = -1

    /** Display name */
    @Column(name = "display_name")
    var displayName: String? = null

    /** */
    @Version
    @Column(name = "version")
    var version: Int = -1
}
